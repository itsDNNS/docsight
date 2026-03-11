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

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--check") == 0) {
        int sock = open_icmp_socket();
        if (sock < 0) {
            perror("socket");
            return 2;
        }
        close(sock);
        puts("ok");
        return 0;
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

    int sock = open_icmp_socket();
    if (sock < 0) {
        perror("socket");
        return 2;
    }

    struct sockaddr_in dest;
    memset(&dest, 0, sizeof(dest));
    if (resolve_ipv4(host, &dest) != 0) {
        close(sock);
        return 2;
    }

    unsigned char packet[sizeof(struct icmphdr) + PAYLOAD_SIZE];
    memset(packet, 0, sizeof(packet));
    struct icmphdr *hdr = (struct icmphdr *)packet;
    hdr->type = ICMP_ECHO;
    hdr->code = 0;
    hdr->un.echo.id = htons((unsigned short)(getpid() & 0xFFFF));
    hdr->un.echo.sequence = htons(1);
    hdr->checksum = icmp_checksum(packet, sizeof(packet));

    struct timeval start;
    if (gettimeofday(&start, NULL) != 0) {
        perror("gettimeofday");
        close(sock);
        return 2;
    }

    if (sendto(sock, packet, sizeof(packet), 0, (struct sockaddr *)&dest, sizeof(dest)) < 0) {
        perror("sendto");
        close(sock);
        return 2;
    }

    for (;;) {
        struct timeval now;
        if (gettimeofday(&now, NULL) != 0) {
            perror("gettimeofday");
            close(sock);
            return 2;
        }

        long elapsed_ms = (now.tv_sec - start.tv_sec) * 1000L
            + (now.tv_usec - start.tv_usec) / 1000L;
        long remaining_ms = timeout_ms - elapsed_ms;
        if (remaining_ms <= 0) {
            puts("TIMEOUT");
            close(sock);
            return 1;
        }

        fd_set readfds;
        FD_ZERO(&readfds);
        FD_SET(sock, &readfds);

        struct timeval tv;
        tv.tv_sec = remaining_ms / 1000L;
        tv.tv_usec = (remaining_ms % 1000L) * 1000L;

        int ready = select(sock + 1, &readfds, NULL, NULL, &tv);
        if (ready < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("select");
            close(sock);
            return 2;
        }
        if (ready == 0) {
            puts("TIMEOUT");
            close(sock);
            return 1;
        }

        unsigned char buffer[1024];
        ssize_t received = recvfrom(sock, buffer, sizeof(buffer), 0, NULL, NULL);
        if (received < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("recvfrom");
            close(sock);
            return 2;
        }

        if (received < (ssize_t)(20 + sizeof(struct icmphdr))) {
            continue;
        }

        struct icmphdr *reply = (struct icmphdr *)(buffer + 20);
        if (reply->type == ICMP_ECHOREPLY
            && reply->un.echo.id == hdr->un.echo.id
            && reply->un.echo.sequence == hdr->un.echo.sequence) {
            struct timeval end;
            if (gettimeofday(&end, NULL) != 0) {
                perror("gettimeofday");
                close(sock);
                return 2;
            }
            double latency_ms = (double)(end.tv_sec - start.tv_sec) * 1000.0
                + (double)(end.tv_usec - start.tv_usec) / 1000.0;
            printf("%.2f\n", latency_ms);
            close(sock);
            return 0;
        }
    }
}
