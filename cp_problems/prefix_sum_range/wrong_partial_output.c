// WRONG: prints answers on one line (format mismatch).
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    int n, q;
    if (scanf("%d %d", &n, &q) != 2) return 0;

    long long *pref = (long long *)malloc((size_t)(n + 1) * sizeof(long long));
    if (!pref) return 0;
    pref[0] = 0;

    for (int i = 1; i <= n; i++) {
        long long x;
        scanf("%lld", &x);
        pref[i] = pref[i - 1] + x;
    }

    for (int i = 0; i < q; i++) {
        int l, r;
        scanf("%d %d", &l, &r);
        long long ans = pref[r] - pref[l - 1];
        if (i) putchar(' ');
        printf("%lld", ans); // should be newline
    }
    putchar('\n');

    free(pref);
    return 0;
}

