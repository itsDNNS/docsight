/*
 * docsight-traceroute-helper — setuid ICMP traceroute for DOCSight
 *
 * Usage: docsight-traceroute-helper [--check] <host> [max_hops] [timeout_ms]
 *
 * Output per hop (tab-separated):
 *   hop_index\thop_ip\tlatency_ms\tprobes_responded
 * Timeout hops:
 *   hop_index\t*\t-1\t0
 *
 * Exit: 0 = target reached, 1 = max hops exceeded, 2 = error
 *
 * Dual-stack: resolves with AF_UNSPEC and traces over ICMPv4 or ICMPv6
 * depending on the resolved address family. The output format does not
 * encode the family — callers (the Python wrapper) treat hop_ip as an
 * opaque string and the v6 textual form fits because tab is the separator.
 */

#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <netinet/icmp6.h>
#include <netinet/in.h>
#include <netinet/ip.h>
#include <netinet/ip6.h>
#include <netinet/ip_icmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/types.h>
#include <unistd.h>

#define DEFAULT_MAX_HOPS   30
#define DEFAULT_TIMEOUT_MS 2000
#define PROBES_PER_HOP     3
#define PAYLOAD_SIZE       32

static unsigned short icmp_checksum(const void *buf, int len) {
    const unsigned short *data = buf;
    unsigned int sum = 0;

    while (len > 1) {
        sum += *data++;
        len -= 2;
    }
    if (len == 1) {
        sum += *(const unsigned char *)data;
    }
    sum = (sum >> 16) + (sum & 0xFFFF);
    sum += (sum >> 16);
    return (unsigned short)(~sum);
}

static int open_icmp_socket(int family) {
    if (family == AF_INET6) {
        return socket(AF_INET6, SOCK_RAW, IPPROTO_ICMPV6);
    }
    return socket(AF_INET, SOCK_RAW, IPPROTO_ICMP);
}

/* Resolve host with AF_UNSPEC and return the first usable AF_INET/AF_INET6
 * entry. Caller must freeaddrinfo(*out_list); the returned chosen pointer
 * aliases into that list. Single-target traceroute does not need TCP-style
 * cross-family fallback — the user asked to trace to a specific host, so we
 * commit to one resolved family in resolver order (matches what TCP/UDP
 * would do for the same hostname). */
static int resolve_host(const char *host,
                        struct addrinfo **out_list,
                        struct addrinfo **out_chosen) {
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    int rc;

    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_RAW;
    /* No service: SOCK_RAW + numeric service trips EAI_SERVICE on glibc. */

    rc = getaddrinfo(host, NULL, &hints, &result);
    if (rc != 0) {
        fprintf(stderr, "%s\n", gai_strerror(rc));
        return -1;
    }

    struct addrinfo *chosen = NULL;
    for (struct addrinfo *ai = result; ai != NULL; ai = ai->ai_next) {
        if (ai->ai_family == AF_INET || ai->ai_family == AF_INET6) {
            chosen = ai;
            break;
        }
    }
    if (chosen == NULL) {
        freeaddrinfo(result);
        fprintf(stderr, "no usable address\n");
        return -1;
    }

    *out_list = result;
    *out_chosen = chosen;
    return 0;
}

static int set_hop_limit(int sock, int family, int ttl) {
    if (family == AF_INET6) {
        return setsockopt(sock, IPPROTO_IPV6, IPV6_UNICAST_HOPS,
                          &ttl, sizeof(ttl));
    }
    return setsockopt(sock, IPPROTO_IP, IP_TTL, &ttl, sizeof(ttl));
}

static int build_echo_packet(int family, unsigned short ident,
                             unsigned short seq, unsigned char *packet) {
    if (family == AF_INET6) {
        size_t len = sizeof(struct icmp6_hdr) + PAYLOAD_SIZE;
        memset(packet, 0, len);
        struct icmp6_hdr *hdr = (struct icmp6_hdr *)packet;
        hdr->icmp6_type = ICMP6_ECHO_REQUEST;
        hdr->icmp6_code = 0;
        hdr->icmp6_id = htons(ident);
        hdr->icmp6_seq = htons(seq);
        /* Kernel fills the ICMPv6 checksum on IPPROTO_ICMPV6 raw sockets. */
        hdr->icmp6_cksum = 0;
        return (int)len;
    }
    size_t len = sizeof(struct icmphdr) + PAYLOAD_SIZE;
    memset(packet, 0, len);
    struct icmphdr *hdr = (struct icmphdr *)packet;
    hdr->type = ICMP_ECHO;
    hdr->code = 0;
    hdr->un.echo.id = htons(ident);
    hdr->un.echo.sequence = htons(seq);
    hdr->checksum = icmp_checksum(packet, (int)len);
    return (int)len;
}

/* Returns 1 when buf carries our hop response (ident+seq match):
 *  - on Echo Reply: *reached = 1
 *  - on Time Exceeded (TTL): *reached = 0
 * Returns 0 when buf is unrelated (keep waiting).
 *
 * IPv4 (IPPROTO_ICMP raw) delivers the full IP datagram, so the outer IP
 * header must be skipped using ip_hl. The Time-Exceeded payload embeds the
 * original packet: outer-IP + outer-ICMP(8) + inner-IP + inner-ICMP(8). */
static int classify_reply4(const unsigned char *buf, ssize_t n,
                           unsigned short ident, unsigned short seq,
                           int *reached) {
    *reached = 0;
    if (n < (ssize_t)(sizeof(struct ip) + sizeof(struct icmphdr))) {
        return 0;
    }
    const struct ip *ip4 = (const struct ip *)buf;
    size_t ip_hlen = (size_t)ip4->ip_hl * 4;
    if (ip_hlen < sizeof(struct ip)) ip_hlen = sizeof(struct ip);
    if ((size_t)n < ip_hlen + sizeof(struct icmphdr)) {
        return 0;
    }
    const struct icmphdr *outer = (const struct icmphdr *)(buf + ip_hlen);

    if (outer->type == ICMP_ECHOREPLY
        && outer->un.echo.id == htons(ident)
        && outer->un.echo.sequence == htons(seq)) {
        *reached = 1;
        return 1;
    }

    if (outer->type == ICMP_TIME_EXCEEDED && outer->code == ICMP_EXC_TTL) {
        size_t need = ip_hlen + sizeof(struct icmphdr)
                    + sizeof(struct ip) + sizeof(struct icmphdr);
        if ((size_t)n < need) return 0;
        const struct icmphdr *inner = (const struct icmphdr *)
            (buf + ip_hlen + sizeof(struct icmphdr) + sizeof(struct ip));
        if (inner->un.echo.id == htons(ident)
            && inner->un.echo.sequence == htons(seq)) {
            return 1;
        }
    }
    return 0;
}

/* IPv6 (IPPROTO_ICMPV6 raw) delivers only the ICMPv6 message — there is
 * no outer IPv6 header in the buffer. The Time-Exceeded payload embeds
 * the original packet: outer-ICMPv6(8) + inner-IPv6(40) + inner-ICMPv6(8). */
static int classify_reply6(const unsigned char *buf, ssize_t n,
                           unsigned short ident, unsigned short seq,
                           int *reached) {
    *reached = 0;
    if (n < (ssize_t)sizeof(struct icmp6_hdr)) {
        return 0;
    }
    const struct icmp6_hdr *outer = (const struct icmp6_hdr *)buf;

    if (outer->icmp6_type == ICMP6_ECHO_REPLY
        && outer->icmp6_id == htons(ident)
        && outer->icmp6_seq == htons(seq)) {
        *reached = 1;
        return 1;
    }

    if (outer->icmp6_type == ICMP6_TIME_EXCEEDED) {
        size_t need = sizeof(struct icmp6_hdr) + sizeof(struct ip6_hdr)
                    + sizeof(struct icmp6_hdr);
        if ((size_t)n < need) return 0;
        const struct icmp6_hdr *inner = (const struct icmp6_hdr *)
            (buf + sizeof(struct icmp6_hdr) + sizeof(struct ip6_hdr));
        if (inner->icmp6_id == htons(ident)
            && inner->icmp6_seq == htons(seq)) {
            return 1;
        }
    }
    return 0;
}

static void format_addr(int family, const struct sockaddr_storage *from,
                        char *out, size_t outlen) {
    if (family == AF_INET6) {
        const struct sockaddr_in6 *s6 = (const struct sockaddr_in6 *)from;
        inet_ntop(AF_INET6, &s6->sin6_addr, out, (socklen_t)outlen);
    } else {
        const struct sockaddr_in *s4 = (const struct sockaddr_in *)from;
        inet_ntop(AF_INET, &s4->sin_addr, out, (socklen_t)outlen);
    }
}

/* Send one ICMP/ICMPv6 Echo Request with given TTL, wait for a reply.
 * Returns latency in ms (>= 0) on response, -1 on timeout/error.
 * Sets *resp_ip to the responding hop address. Sets *reached if the target
 * itself replied. */
static double send_probe(int sock, int family,
                         const struct sockaddr *dest, socklen_t dest_len,
                         unsigned short ident, unsigned short seq,
                         int ttl, int timeout_ms,
                         char *resp_ip, size_t resp_ip_len, int *reached) {
    /* struct icmp6_hdr and struct icmphdr are both 8 bytes; one buffer fits
     * either family with the same payload size. */
    unsigned char packet[sizeof(struct icmp6_hdr) + PAYLOAD_SIZE];
    struct timeval start;

    *reached = 0;
    resp_ip[0] = '\0';

    if (set_hop_limit(sock, family, ttl) < 0) {
        return -1;
    }

    int packet_len = build_echo_packet(family, ident, seq, packet);

    if (gettimeofday(&start, NULL) != 0) return -1;

    if (sendto(sock, packet, (size_t)packet_len, 0, dest, dest_len) < 0) {
        return -1;
    }

    for (;;) {
        struct timeval now;
        if (gettimeofday(&now, NULL) != 0) return -1;

        long elapsed_ms = (now.tv_sec - start.tv_sec) * 1000L
                        + (now.tv_usec - start.tv_usec) / 1000L;
        long remaining_ms = timeout_ms - elapsed_ms;
        if (remaining_ms <= 0) return -1;

        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(sock, &fds);

        struct timeval tv;
        tv.tv_sec  = remaining_ms / 1000L;
        tv.tv_usec = (remaining_ms % 1000L) * 1000L;

        int ready = select(sock + 1, &fds, NULL, NULL, &tv);
        if (ready < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (ready == 0) return -1;

        unsigned char buf[1500];
        struct sockaddr_storage from;
        socklen_t fromlen = sizeof(from);
        ssize_t n = recvfrom(sock, buf, sizeof(buf), 0,
                             (struct sockaddr *)&from, &fromlen);
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }

        int matched = (family == AF_INET6)
            ? classify_reply6(buf, n, ident, seq, reached)
            : classify_reply4(buf, n, ident, seq, reached);
        if (!matched) {
            continue;
        }

        struct timeval end;
        if (gettimeofday(&end, NULL) != 0) return -1;
        double ms = (double)(end.tv_sec - start.tv_sec) * 1000.0
                  + (double)(end.tv_usec - start.tv_usec) / 1000.0;
        format_addr(family, &from, resp_ip, resp_ip_len);
        return ms;
    }
}

static int run_check(void) {
    int sock4 = open_icmp_socket(AF_INET);
    int sock6 = open_icmp_socket(AF_INET6);
    if (sock4 < 0 && sock6 < 0) {
        perror("socket");
        return 2;
    }
    if (seteuid(getuid()) != 0) {
        perror("seteuid");
        if (sock4 >= 0) close(sock4);
        if (sock6 >= 0) close(sock6);
        return 2;
    }
    if (sock4 >= 0) close(sock4);
    if (sock6 >= 0) close(sock6);
    puts("ok");
    return 0;
}

int main(int argc, char **argv) {
    if (argc >= 2 && strcmp(argv[1], "--check") == 0) {
        return run_check();
    }

    if (argc < 2 || argc > 4) {
        fprintf(stderr, "usage: %s [--check] <host> [max_hops] [timeout_ms]\n",
                argv[0]);
        return 2;
    }

    const char *host = argv[1];
    int max_hops   = (argc >= 3) ? atoi(argv[2]) : DEFAULT_MAX_HOPS;
    int timeout_ms = (argc >= 4) ? atoi(argv[3]) : DEFAULT_TIMEOUT_MS;

    if (max_hops <= 0 || max_hops > 255) {
        fprintf(stderr, "invalid max_hops (1-255)\n");
        return 2;
    }
    if (timeout_ms <= 0) {
        fprintf(stderr, "invalid timeout_ms\n");
        return 2;
    }

    /* Open raw sockets BEFORE name resolution. The setuid helper model
     * forbids running NSS/DNS code while euid is root, so raw-socket
     * creation must consume the elevated privilege first. We open both
     * families up front because the family the resolver will choose is
     * not known until after seteuid(getuid()) has run. Failure is only
     * reported when neither family is available. */
    int sock4 = open_icmp_socket(AF_INET);
    int sock6 = open_icmp_socket(AF_INET6);
    if (sock4 < 0 && sock6 < 0) {
        perror("socket");
        return 2;
    }

    /* Drop privileges immediately, before any name resolution runs. */
    if (seteuid(getuid()) != 0) {
        perror("seteuid");
        if (sock4 >= 0) close(sock4);
        if (sock6 >= 0) close(sock6);
        return 2;
    }

    /* Now safe to invoke NSS/DNS resolution (AF_UNSPEC). */
    struct addrinfo *ai_list = NULL;
    struct addrinfo *chosen = NULL;
    if (resolve_host(host, &ai_list, &chosen) != 0) {
        if (sock4 >= 0) close(sock4);
        if (sock6 >= 0) close(sock6);
        return 2;
    }

    int family = chosen->ai_family;
    int sock;
    if (family == AF_INET6) {
        if (sock6 < 0) {
            fprintf(stderr, "no IPv6 raw socket available\n");
            if (sock4 >= 0) close(sock4);
            freeaddrinfo(ai_list);
            return 2;
        }
        sock = sock6;
        if (sock4 >= 0) close(sock4);
    } else {
        if (sock4 < 0) {
            fprintf(stderr, "no IPv4 raw socket available\n");
            if (sock6 >= 0) close(sock6);
            freeaddrinfo(ai_list);
            return 2;
        }
        sock = sock4;
        if (sock6 >= 0) close(sock6);
    }

    /* Copy destination off the addrinfo so we can free the list before
     * the per-hop loop. */
    struct sockaddr_storage dest;
    socklen_t dest_len = (socklen_t)chosen->ai_addrlen;
    memcpy(&dest, chosen->ai_addr, chosen->ai_addrlen);
    freeaddrinfo(ai_list);

    unsigned short ident = (unsigned short)(getpid() & 0xFFFF);
    unsigned short seq = 0;
    int target_reached = 0;

    for (int hop = 1; hop <= max_hops; hop++) {
        double best_ms = -1;
        int responded = 0;
        char hop_ip[INET6_ADDRSTRLEN];
        hop_ip[0] = '\0';

        for (int p = 0; p < PROBES_PER_HOP; p++) {
            seq++;
            char probe_ip[INET6_ADDRSTRLEN];
            int reached = 0;
            double ms = send_probe(sock, family,
                                   (const struct sockaddr *)&dest, dest_len,
                                   ident, seq, hop, timeout_ms,
                                   probe_ip, sizeof(probe_ip), &reached);
            if (ms >= 0) {
                responded++;
                if (best_ms < 0 || ms < best_ms) {
                    best_ms = ms;
                    /* Use the IP from the first successful probe. */
                    if (hop_ip[0] == '\0') {
                        memcpy(hop_ip, probe_ip, sizeof(hop_ip));
                    }
                }
                if (reached) target_reached = 1;
            }
        }

        if (responded == 0) {
            printf("%d\t*\t-1\t0\n", hop);
        } else {
            printf("%d\t%s\t%.2f\t%d\n", hop, hop_ip, best_ms, responded);
        }
        fflush(stdout);

        if (target_reached) {
            close(sock);
            return 0;
        }
    }

    close(sock);
    return 1;
}
