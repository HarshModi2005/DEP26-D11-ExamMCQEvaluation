# Range Sum Queries (Prefix Sums)

You are given an array of `N` integers and `Q` queries. Each query asks for the sum of elements in the subarray from index `L` to `R` (1-indexed, inclusive).

Answer all queries.

## Input
- First line: two integers `N` and `Q`
- Second line: `N` integers `A1..AN`
- Next `Q` lines: two integers `L` and `R`

## Output
Print `Q` lines. For each query, print the subarray sum `A[L] + ... + A[R]`.

## Constraints
- `1 <= N, Q <= 200000`
- `-10^9 <= Ai <= 10^9`
- `1 <= L <= R <= N`

## Notes
- Use prefix sums to answer each query in `O(1)` after `O(N)` preprocessing.
- Use 64-bit (`long long`) for sums.

