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
 */

#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
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

static int open_icmp_socket(void) {
    return socket(AF_INET, SOCK_RAW, IPPROTO_ICMP);
}

static int resolve_ipv4(const char *host, struct sockaddr_in *addr) {
    struct addrinfo hints;
    struct addrinfo *result = NULL;
    int rc;

    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_RAW;
    hints.ai_protocol = IPPROTO_ICMP;

    rc = getaddrinfo(host, NULL, &hints, &result);
    if (rc != 0) {
        fprintf(stderr, "%s\n", gai_strerror(rc));
        return -1;
    }

    memcpy(addr, result->ai_addr, sizeof(*addr));
    freeaddrinfo(result);
    return 0;
}

/* Send one ICMP Echo Request with given TTL, wait for reply.
 * Returns latency in ms (>= 0) on response, -1 on timeout.
 * Sets *resp_ip to the responding hop address. Sets *reached if target replied. */
static double send_probe(int sock, const struct sockaddr_in *dest,
                         unsigned short ident, unsigned short seq,
                         int ttl, int timeout_ms,
                         char *resp_ip, size_t resp_ip_len, int *reached) {
    unsigned char packet[sizeof(struct icmphdr) + PAYLOAD_SIZE];
    struct icmphdr *hdr = (struct icmphdr *)packet;
    struct timeval start, now;

    *reached = 0;
    resp_ip[0] = '\0';

    if (setsockopt(sock, IPPROTO_IP, IP_TTL, &ttl, sizeof(ttl)) < 0) {
        return -1;
    }

    memset(packet, 0, sizeof(packet));
    hdr->type = ICMP_ECHO;
    hdr->code = 0;
    hdr->un.echo.id = htons(ident);
    hdr->un.echo.sequence = htons(seq);
    hdr->checksum = icmp_checksum(packet, sizeof(packet));

    if (gettimeofday(&start, NULL) != 0) return -1;

    if (sendto(sock, packet, sizeof(packet), 0,
               (const struct sockaddr *)dest, sizeof(*dest)) < 0) {
        return -1;
    }

    for (;;) {
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

        unsigned char buf[1024];
        struct sockaddr_in from;
        socklen_t fromlen = sizeof(from);
        ssize_t n = recvfrom(sock, buf, sizeof(buf), 0,
                             (struct sockaddr *)&from, &fromlen);
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (n < (ssize_t)(20 + sizeof(struct icmphdr))) continue;

        struct icmphdr *reply = (struct icmphdr *)(buf + 20);

        if (reply->type == ICMP_ECHOREPLY
            && reply->un.echo.id == htons(ident)
            && reply->un.echo.sequence == htons(seq)) {
            struct timeval end;
            if (gettimeofday(&end, NULL) != 0) return -1;
            double ms = (double)(end.tv_sec - start.tv_sec) * 1000.0
                      + (double)(end.tv_usec - start.tv_usec) / 1000.0;
            inet_ntop(AF_INET, &from.sin_addr, resp_ip, resp_ip_len);
            *reached = 1;
            return ms;
        }

        if (reply->type == ICMP_TIME_EXCEEDED && reply->code == ICMP_EXC_TTL) {
            /* Embedded original packet: outer IP(20) + ICMP TTL_EXCEEDED(8) + inner IP(20) + inner ICMP(8) */
            if (n < (ssize_t)(20 + 8 + 20 + 8)) continue;
            struct icmphdr *inner = (struct icmphdr *)(buf + 20 + 8 + 20);
            if (inner->un.echo.id == htons(ident)
                && inner->un.echo.sequence == htons(seq)) {
                struct timeval end;
                if (gettimeofday(&end, NULL) != 0) return -1;
                double ms = (double)(end.tv_sec - start.tv_sec) * 1000.0
                          + (double)(end.tv_usec - start.tv_usec) / 1000.0;
                inet_ntop(AF_INET, &from.sin_addr, resp_ip, resp_ip_len);
                return ms;
            }
        }
        /* Not our packet, keep waiting */
    }
}

int main(int argc, char **argv) {
    if (argc >= 2 && strcmp(argv[1], "--check") == 0) {
        int sock = open_icmp_socket();
        if (sock < 0) {
            perror("socket");
            return 2;
        }
        if (seteuid(getuid()) != 0) {
            perror("seteuid");
            close(sock);
            return 2;
        }
        close(sock);
        puts("ok");
        return 0;
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

    /* Open raw socket (requires CAP_NET_RAW or setuid root) */
    int sock = open_icmp_socket();
    if (sock < 0) {
        perror("socket");
        return 2;
    }

    /* Immediately drop privileges */
    if (seteuid(getuid()) != 0) {
        perror("seteuid");
        close(sock);
        return 2;
    }

    struct sockaddr_in dest;
    memset(&dest, 0, sizeof(dest));
    if (resolve_ipv4(host, &dest) != 0) {
        close(sock);
        return 2;
    }

    unsigned short ident = (unsigned short)(getpid() & 0xFFFF);
    unsigned short seq = 0;
    int target_reached = 0;

    for (int hop = 1; hop <= max_hops; hop++) {
        double best_ms = -1;
        int responded = 0;
        char hop_ip[INET_ADDRSTRLEN];
        hop_ip[0] = '\0';

        for (int p = 0; p < PROBES_PER_HOP; p++) {
            seq++;
            char probe_ip[INET_ADDRSTRLEN];
            int reached = 0;
            double ms = send_probe(sock, &dest, ident, seq,
                                   hop, timeout_ms,
                                   probe_ip, sizeof(probe_ip), &reached);
            if (ms >= 0) {
                responded++;
                if (best_ms < 0 || ms < best_ms) {
                    best_ms = ms;
                    /* Use the IP from the first successful probe */
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
