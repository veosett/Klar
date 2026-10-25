

def is_palindrome(text: str) -> bool:
    """
    Checks if given string is a palindrome
    >>> is_palindrome('')
    True
    >>> is_palindrome('aba')
    True
    >>> is_palindrome('aaaaa')
    True
    >>> is_palindrome('zbcd')
    False
    """
    ### Canonical solution below ###
    for i in range(len(text)):
        if text[i] != text[len(text) - 1 - i]:
            return False
    return True
