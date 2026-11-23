def f(n, m):
    need = m - n
    out = {"need": need}
    if need <= 0:
        if not need:
            return out
        big = 0
        if not big:
            out["short"] = 1
            return out
        return out
    return out
print(f(3, 2), f(1, 2))
