#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
int main(void) {
    struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
    int n = 100000;
    char **parts = malloc(sizeof(char *) * n);
    size_t total = 0;
    for (int i = 0; i < n; i++) { char buf[32]; int len = sprintf(buf, "item%d", i); parts[i] = malloc(len + 1); memcpy(parts[i], buf, len + 1); total += len + 1; }
    char *joined = malloc(total); size_t pos = 0;
    for (int i = 0; i < n; i++) { size_t len = strlen(parts[i]); memcpy(joined + pos, parts[i], len); pos += len; if (i + 1 < n) joined[pos++] = ','; }
    joined[pos] = 0;
    long sevens = 0; char *start = joined;
    for (char *p = joined;; p++) { if (*p == ',' || *p == 0) { if (p > start && p[-1] == '7') sevens++; if (*p == 0) break; start = p + 1; } }
    clock_gettime(CLOCK_MONOTONIC, &b);
    printf("result=%ld,%zu\ntime_ms=%.3f\n", sevens, strlen(joined), (b.tv_sec - a.tv_sec) * 1e3 + (b.tv_nsec - a.tv_nsec) / 1e6);
    return 0;
}
