def inventory(orders: list[str], stock: dict[str, int]) -> list[str]:
    left = dict(stock)
    filled: list[str] = []
    for order in orders:
        parts = order.split(" ")
        oid = parts[0]
        bad = ValueError("bad order " + oid)
        if len(parts) != 2 or oid == "":
            raise bad
        need: dict[str, int] = {}
        for item in parts[1].split(","):
            kv = item.split(":")
            if len(kv) != 2 or kv[0] == "" or not (kv[1].isascii() and kv[1].isdigit()) or int(kv[1]) == 0:
                raise bad
            if kv[0] not in stock:
                raise bad
            need[kv[0]] = need.get(kv[0], 0) + int(kv[1])
        if all(left[k] >= v for k, v in need.items()):
            for k, v in need.items():
                left[k] -= v
            filled.append(oid)
    return filled
