def is_valid_email(s: str) -> bool:
    if " " in s or s.count("@") != 1:
        return False
    local, domain = s.split("@")
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".") \
        and ".." not in domain
