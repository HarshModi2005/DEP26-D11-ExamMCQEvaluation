#include <stdio.h>
#include <stdlib.h>

static inline int read_int(int *out) {
    int c = getchar_unlocked();
    while (c != EOF && c <= ' ') c = getchar_unlocked();
    if (c == EOF) return 0;
    int sign = 1;
    if (c == '-') {
        sign = -1;
        c = getchar_unlocked();
    }
    long long v = 0;
    while (c > ' ') {
        v = v * 10 + (c - '0');
        c = getchar_unlocked();
    }
    *out = (int)(v * sign);
    return 1;
}

static inline int read_ll(long long *out) {
    int c = getchar_unlocked();
    while (c != EOF && c <= ' ') c = getchar_unlocked();
    if (c == EOF) return 0;
    long long sign = 1;
    if (c == '-') {
        sign = -1;
        c = getchar_unlocked();
    }
    long long v = 0;
    while (c > ' ') {
        v = v * 10 + (c - '0');
        c = getchar_unlocked();
    }
    *out = v * sign;
    return 1;
}

int main(void) {
    int n, q;
    if (!read_int(&n) || !read_int(&q)) return 0;

    long long *pref = (long long *)malloc((size_t)(n + 1) * sizeof(long long));
    if (!pref) return 0;
    pref[0] = 0;

    for (int i = 1; i <= n; i++) {
        long long x;
        read_ll(&x);
        pref[i] = pref[i - 1] + x;
    }

    for (int i = 0; i < q; i++) {
        int l, r;
        read_int(&l);
        read_int(&r);
        long long ans = pref[r] - pref[l - 1];
        printf("%lld\n", ans);
    }

    free(pref);
    return 0;
}

