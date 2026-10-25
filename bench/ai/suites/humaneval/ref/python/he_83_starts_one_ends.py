
def starts_one_ends(n: int) -> int:
    """
    Given a positive integer n, return the count of the numbers of n-digit
    positive integers that start or end with 1.
    """
    ### Canonical solution below ###
    if n == 1: return 1
    return 18 * (10 ** (n - 2))
