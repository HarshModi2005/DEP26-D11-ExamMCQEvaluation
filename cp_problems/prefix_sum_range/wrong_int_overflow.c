// WRONG: uses 32-bit int prefix sums -> overflows on large values.
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    int n, q;
    if (scanf("%d %d", &n, &q) != 2) return 0;

    int *pref = (int *)malloc((size_t)(n + 1) * sizeof(int));
    if (!pref) return 0;
    pref[0] = 0;

    for (int i = 1; i <= n; i++) {
        int x;
        scanf("%d", &x);
        pref[i] = pref[i - 1] + x;
    }

    for (int i = 0; i < q; i++) {
        int l, r;
        scanf("%d %d", &l, &r);
        int ans = pref[r] - pref[l - 1];
        printf("%d\n", ans);
    }

    free(pref);
    return 0;
}

