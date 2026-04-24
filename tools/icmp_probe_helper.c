#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <netinet/icmp6.h>
#include <netinet/in.h>
#include <netinet/ip_icmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/types.h>
#include <unistd.h>

#define DEFAULT_TIMEOUT_MS 2000
#define PAYLOAD_SIZE 32

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

static long elapsed_ms_since(const struct timeval *start) {
    struct timeval now;
    if (gettimeofday(&now, NULL) != 0) {
        return -1;
    }
    return (now.tv_sec - start->tv_sec) * 1000L
         + (now.tv_usec - start->tv_usec) / 1000L;
}

/* Split the remaining overall budget evenly across the remaining addresses
 * so a silent first address cannot starve later addresses of their wait. */
static long per_address_budget_ms(long remaining_overall_ms,
                                  int remaining_addresses) {
    if (remaining_addresses <= 0 || remaining_overall_ms <= 0) {
        return 0;
    }
    return remaining_overall_ms / remaining_addresses;
}

static int build_icmp4_echo(unsigned char *buf, unsigned short ident,
                            unsigned short seq) {
    memset(buf, 0, sizeof(struct icmphdr) + PAYLOAD_SIZE);
    struct icmphdr *hdr = (struct icmphdr *)buf;
    hdr->type = ICMP_ECHO;
    hdr->code = 0;
    hdr->un.echo.id = htons(ident);
    hdr->un.echo.sequence = htons(seq);
    hdr->checksum = icmp_checksum(buf, sizeof(struct icmphdr) + PAYLOAD_SIZE);
    return (int)(sizeof(struct icmphdr) + PAYLOAD_SIZE);
}

static int build_icmp6_echo(unsigned char *buf, unsigned short ident,
                            unsigned short seq) {
    memset(buf, 0, sizeof(struct icmp6_hdr) + PAYLOAD_SIZE);
    struct icmp6_hdr *hdr = (struct icmp6_hdr *)buf;
    hdr->icmp6_type = ICMP6_ECHO_REQUEST;
    hdr->icmp6_code = 0;
    hdr->icmp6_id = htons(ident);
    hdr->icmp6_seq = htons(seq);
    /* Kernel fills ICMPv6 checksum for IPPROTO_ICMPV6 raw sockets. */
    hdr->icmp6_cksum = 0;
    return (int)(sizeof(struct icmp6_hdr) + PAYLOAD_SIZE);
}

static int match_icmp4_reply(const unsigned char *buf, ssize_t len,
                             unsigned short ident, unsigned short seq) {
    /* AF_INET raw sockets receive the full IP datagram; skip the IP header. */
    if (len < (ssize_t)(sizeof(struct ip) + sizeof(struct icmphdr))) {
        return 0;
    }
    const struct ip *ip_hdr = (const struct ip *)buf;
    size_t ip_hlen = (size_t)ip_hdr->ip_hl * 4;
    if ((size_t)len < ip_hlen + sizeof(struct icmphdr)) {
        return 0;
    }
    const struct icmphdr *reply = (const struct icmphdr *)(buf + ip_hlen);
    return reply->type == ICMP_ECHOREPLY
        && reply->un.echo.id == htons(ident)
        && reply->un.echo.sequence == htons(seq);
}

static int match_icmp6_reply(const unsigned char *buf, ssize_t len,
                             unsigned short ident, unsigned short seq) {
    /* IPPROTO_ICMPV6 raw sockets deliver only the ICMPv6 message. */
    if (len < (ssize_t)sizeof(struct icmp6_hdr)) {
        return 0;
    }
    const struct icmp6_hdr *reply = (const struct icmp6_hdr *)buf;
    return reply->icmp6_type == ICMP6_ECHO_REPLY
        && reply->icmp6_id == htons(ident)
        && reply->icmp6_seq == htons(seq);
}

static int run_check(void) {
    int sock4 = open_icmp_socket(AF_INET);
    int sock6 = open_icmp_socket(AF_INET6);
    if (sock4 < 0 && sock6 < 0) {
        perror("socket");
        return 2;
    }
    if (sock4 >= 0) {
        close(sock4);
    }
    if (sock6 >= 0) {
        close(sock6);
    }
    puts("ok");
    return 0;
}

/* Attempt to probe one resolved address. Returns 0 on reply,
 * 1 on sent-but-no-reply, -1 when this address could not be used
 * (e.g. socket/sendto failed). latency_out is filled on success.
 *
 * The wait is bounded by min(per_address_budget_ms, total_budget_ms - elapsed):
 * a silent first address must not consume the full overall budget, or later
 * addresses in the addrinfo list would never be probed. */
static int probe_address(const struct addrinfo *ai,
                         unsigned short ident,
                         unsigned short seq,
                         long attempt_budget_ms,
                         long total_budget_ms,
                         const struct timeval *overall_start,
                         double *latency_out) {
    int sock = open_icmp_socket(ai->ai_family);
    if (sock < 0) {
        perror("socket");
        return -1;
    }

    unsigned char packet[sizeof(struct icmp6_hdr) + PAYLOAD_SIZE];
    int packet_len = (ai->ai_family == AF_INET6)
        ? build_icmp6_echo(packet, ident, seq)
        : build_icmp4_echo(packet, ident, seq);

    struct timeval attempt_start;
    if (gettimeofday(&attempt_start, NULL) != 0) {
        perror("gettimeofday");
        close(sock);
        return -1;
    }

    if (sendto(sock, packet, (size_t)packet_len, 0,
               ai->ai_addr, ai->ai_addrlen) < 0) {
        perror("sendto");
        close(sock);
        return -1;
    }

    for (;;) {
        long elapsed_overall = elapsed_ms_since(overall_start);
        if (elapsed_overall < 0) {
            perror("gettimeofday");
            close(sock);
            return 1;
        }
        long remaining_overall = total_budget_ms - elapsed_overall;
        if (remaining_overall <= 0) {
            close(sock);
            return 1;
        }

        long elapsed_attempt = elapsed_ms_since(&attempt_start);
        if (elapsed_attempt < 0) {
            perror("gettimeofday");
            close(sock);
            return 1;
        }
        long remaining_attempt = attempt_budget_ms - elapsed_attempt;
        if (remaining_attempt <= 0) {
            close(sock);
            return 1;
        }

        long wait_ms = remaining_overall < remaining_attempt
            ? remaining_overall
            : remaining_attempt;

        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(sock, &readfds);
        struct timeval tv;
        tv.tv_sec = wait_ms / 1000L;
        tv.tv_usec = (wait_ms % 1000L) * 1000L;

        int ready = select(sock + 1, &readfds, NULL, NULL, &tv);
        if (ready < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("select");
            close(sock);
            return 1;
        }
        if (ready == 0) {
            close(sock);
            return 1;
        }

        unsigned char buffer[2048];
        ssize_t received = recvfrom(sock, buffer, sizeof(buffer), 0, NULL, NULL);
        if (received < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("recvfrom");
            close(sock);
            return 1;
        }

        int matches = (ai->ai_family == AF_INET6)
            ? match_icmp6_reply(buffer, received, ident, seq)
            : match_icmp4_reply(buffer, received, ident, seq);
        if (!matches) {
            continue;
        }

        struct timeval end;
        if (gettimeofday(&end, NULL) != 0) {
            perror("gettimeofday");
            close(sock);
            return 1;
        }
        *latency_out = (double)(end.tv_sec - attempt_start.tv_sec) * 1000.0
            + (double)(end.tv_usec - attempt_start.tv_usec) / 1000.0;
        close(sock);
        return 0;
    }
}

/* Diagnostic mode: simulate how the main loop would allocate per-address
 * budgets for num_addresses, assuming each attempt consumes its full budget.
 * Prints one budget per line. Used by tests to prove that no address is
 * starved — without this, the Python test would have to run the real helper
 * with raw-socket privileges against an unreachable host. */
static int run_plan(long total_ms, int num_addresses) {
    if (total_ms <= 0 || num_addresses <= 0) {
        fprintf(stderr, "invalid plan args\n");
        return 2;
    }
    long simulated_elapsed = 0;
    int remaining = num_addresses;
    for (int i = 0; i < num_addresses; i++) {
        long remaining_overall = total_ms - simulated_elapsed;
        long budget = per_address_budget_ms(remaining_overall, remaining);
        printf("%ld\n", budget);
        simulated_elapsed += budget;
        remaining--;
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--check") == 0) {
        return run_check();
    }

    if (argc == 4 && strcmp(argv[1], "--plan") == 0) {
        return run_plan(atol(argv[2]), atoi(argv[3]));
    }

    if (argc < 2 || argc > 3) {
        fprintf(stderr, "usage: %s [--check] <host> [timeout_ms]\n", argv[0]);
        return 2;
    }

    const char *host = argv[1];
    int timeout_ms = DEFAULT_TIMEOUT_MS;
    if (argc == 3) {
        timeout_ms = atoi(argv[2]);
        if (timeout_ms <= 0) {
            fprintf(stderr, "invalid timeout_ms\n");
            return 2;
        }
    }

    struct addrinfo hints;
    struct addrinfo *result = NULL;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_RAW;
    /* No service: raw sockets have no port, and Linux returns EAI_SERVICE
     * if a numeric service is supplied with SOCK_RAW. */
    int rc = getaddrinfo(host, NULL, &hints, &result);
    if (rc != 0) {
        fprintf(stderr, "%s\n", gai_strerror(rc));
        return 2;
    }

    struct timeval overall_start;
    if (gettimeofday(&overall_start, NULL) != 0) {
        perror("gettimeofday");
        freeaddrinfo(result);
        return 2;
    }

    unsigned short ident = (unsigned short)(getpid() & 0xFFFF);
    unsigned short seq = 0;
    int any_sent = 0;
    int any_usable_family = 0;

    /* Pre-count usable addresses so per-address budgets can be allocated
     * without giving the first address the entire overall window. */
    int remaining_addresses = 0;
    for (struct addrinfo *ai = result; ai != NULL; ai = ai->ai_next) {
        if (ai->ai_family == AF_INET || ai->ai_family == AF_INET6) {
            remaining_addresses++;
        }
    }

    /* Iterate every resolved address, trying each family until one replies.
     * Mirrors the Python TCP probe semantics: socket/sendto/timeout on the
     * first address must not short-circuit the remaining addresses. */
    for (struct addrinfo *ai = result; ai != NULL; ai = ai->ai_next) {
        if (ai->ai_family != AF_INET && ai->ai_family != AF_INET6) {
            continue;
        }
        any_usable_family = 1;

        long elapsed = elapsed_ms_since(&overall_start);
        if (elapsed < 0) {
            perror("gettimeofday");
            freeaddrinfo(result);
            return 2;
        }
        long remaining_overall = timeout_ms - elapsed;
        if (remaining_overall <= 0) {
            break;
        }

        long per_addr_budget = per_address_budget_ms(
            remaining_overall, remaining_addresses);
        remaining_addresses--;
        if (per_addr_budget <= 0) {
            continue;
        }

        seq++;
        double latency_ms = 0.0;
        int probe_rc = probe_address(ai, ident, seq, per_addr_budget,
                                     timeout_ms, &overall_start, &latency_ms);
        if (probe_rc == 0) {
            printf("%.2f\n", latency_ms);
            freeaddrinfo(result);
            return 0;
        }
        if (probe_rc == 1) {
            any_sent = 1;
        }
        /* probe_rc == -1: socket/sendto failure, try next address. */
    }

    freeaddrinfo(result);

    if (any_sent) {
        puts("TIMEOUT");
        return 1;
    }
    if (!any_usable_family) {
        fprintf(stderr, "no usable address\n");
    }
    return 2;
}
