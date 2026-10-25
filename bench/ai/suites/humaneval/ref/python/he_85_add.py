from typing import List

def add(lst: List[int]) -> int:
    """Given a non-empty list of integers lst. add the even elements that are at odd indices..


    Examples:
        add([4, 2, 6, 7]) ==> 2 
    """
    ### Canonical solution below ###
    return sum([lst[i] for i in range(1, len(lst), 2) if lst[i]%2 == 0])
