import sys
from typing import Any, Callable

from model import Category, Customer, Line, Order, Product, Status, Tier
from analytics import average_order, revenue, revenue_by_city, spend_by_customer
from audit import valid_step
from catalog import average_price, catalog_value, price_band, price_label, sale_price
from commission import commission, commission_rate, commission_total, earned_bonus
from crm import customer_row, display_name, initials, mailing_line, parse_customer, sorted_customers, validate_customer
from dashboard import headline, open_value, status_counts
from discount import discount_for, net_amount
from export import order_row, product_row, status_code
from fraud import risk_score
from invoice import due_note
from loyalty import points_for, redeem_value
from money import avg, fmt, pct, plain
from notify import message_for
from orders import grand_total, is_open, is_revenue, line_total, next_status, release, status_label, subtotal
from picking import can_pack
from refunds import refund_amount, refund_share
from sample import sample_products
from shipping import shipping_cost, surcharge
from tax import order_tax


def prodc(price: int, category: Category) -> Product:
    return Product("S", "item", price, 1.0, category, 2, 1)


def prod(price: int) -> Product:
    return Product("P", "item", price, 1.0, Category.BOOK, 2, 1)


def ln(price: int, qty: int) -> Line:
    return Line("S", qty, price)


def ord(status: Status, items: list[Line], sent: int) -> Order:
    return Order(1, 1, items, status, sent, 1)


def cust(first: str, last: str) -> Customer:
    return Customer(1, first, last, "a@b.org", Tier.BASIC, "Harbour")


def custt(tier: Tier) -> Customer:
    return Customer(1, "Ada", "Lovelace", "a@b.org", tier, "Harbour")


def size(xs: list[Any]) -> int:
    return len(xs)


def mget(m: dict[str, int], key: str) -> int:
    return m.get(key, -1)


def names(cs: list[Customer]) -> list[str]:
    return [f"{c.first_name} {c.last_name}" for c in cs]


def Some(x: Any) -> Any:
    return x


passed = 0
failed = 0


def equal(actual: Any, expected: Any) -> None:
    if actual != expected:
        raise AssertionError(f"got {actual!r}, expected {expected!r}")


def run(name: str, test: Callable[[], None]) -> None:
    global passed, failed
    try:
        test()
        passed += 1
    except Exception as e:  # a crash is a failed check, not the end of the run
        failed += 1
        print(f"FAIL  {name}{chr(10)}      {type(e).__name__}: {e}")



def check_0() -> None:
    equal(fmt(1250), "$12.50")
    equal(plain(1205), "12.05")
    equal(plain(7), "0.07")


run("money: fmt and plain", check_0)


def check_1() -> None:
    equal(pct(125, 0.1), 13)
    equal(avg(5, 2), 3)
    equal(avg(0, 0), 0)


run("money: pct and avg", check_1)


def check_2() -> None:
    equal(price_band(prod(999)), "cheap")
    equal(price_band(prod(1000)), "regular")
    equal(price_band(prod(9999)), "regular")
    equal(price_band(prod(10000)), "premium")


run("catalog: price_band", check_2)


def check_3() -> None:
    equal(sale_price(prod(2000), 0.25), 1500)


run("catalog: sale_price", check_3)


def check_4() -> None:
    equal(average_price([prod(100), prod(101)]), 101)


run("catalog: average_price", check_4)


def check_5() -> None:
    equal(price_label(prod(1250)), "item: $12.50")


run("catalog: price_label", check_5)


def check_6() -> None:
    equal(line_total(ln(1250, 3)), 3750)
    equal(subtotal(ord(Status.PAID, [ln(1000, 2)], 499)), 2000)
    equal(grand_total(ord(Status.PAID, [ln(1000, 2)], 499)), 2499)


run("orders: totals", check_6)


def check_7() -> None:
    equal(order_tax(ord(Status.PAID, [ln(1000, 1)], 0), [prodc(1000, Category.TOY)]), 200)
    equal(order_tax(ord(Status.DRAFT, [ln(1000, 1)], 0), [prodc(1000, Category.TOY)]), 0)


run("tax: order_tax", check_7)


def check_8() -> None:
    equal(discount_for(10000, Tier.GOLD), 1000)
    equal(discount_for(50, Tier.SILVER), 3)


run("discount: discount_for", check_8)


def check_9() -> None:
    equal(net_amount(10000, Tier.BASIC, "FIVE"), 9500)


run("discount: net_amount", check_9)


def check_10() -> None:
    equal(shipping_cost(5000, 1.0), 0)
    equal(shipping_cost(4999, 2.0), 799)


run("shipping: shipping_cost", check_10)


def check_11() -> None:
    equal(surcharge("Harbour"), 750)
    equal(surcharge("Summit"), 1200)
    equal(surcharge("Plain"), 0)


run("shipping: surcharge", check_11)


def check_12() -> None:
    equal(points_for(2599), 2)
    equal(points_for(999), 0)


run("loyalty: points_for", check_12)


def check_13() -> None:
    equal(redeem_value(5), 50)


run("loyalty: redeem_value", check_13)


def check_14() -> None:
    equal(risk_score(ord(Status.PAID, [ln(100000, 1)], 0), cust("Ada", "Lovelace")), 4)
    equal(risk_score(ord(Status.PAID, [ln(30000, 1)], 0), custt(Tier.GOLD)), 1)
    equal(risk_score(ord(Status.PAID, [ln(29999, 1)], 0), custt(Tier.GOLD)), 0)


run("fraud: risk_score", check_14)


def check_15() -> None:
    equal(refund_amount(ord(Status.PAID, [ln(1000, 1)], 0)), 1000)
    equal(refund_amount(ord(Status.SHIPPED, [ln(1000, 1)], 0)), 950)
    equal(refund_amount(ord(Status.DELIVERED, [ln(1000, 1)], 0)), 900)


run("refunds: refund_amount", check_15)


def check_16() -> None:
    equal(due_note(10000), "payable in 14 days")
    equal(due_note(10001), "payable in 30 days")


run("invoice: due_note", check_16)


def check_17() -> None:
    equal(revenue([ord(Status.PAID, [ln(100, 1)], 0), ord(Status.DRAFT, [ln(100, 1)], 0)]), 100)
    equal(average_order([ord(Status.PAID, [ln(100, 1)], 0), ord(Status.PAID, [ln(101, 1)], 0)]), 101)


run("analytics: revenue and average", check_17)


def check_18() -> None:
    equal(mget(revenue_by_city([ord(Status.PAID, [ln(500, 1)], 0)], [cust("Ada", "Lovelace")]), "Harbour"), 500)


run("analytics: revenue_by_city", check_18)


def check_19() -> None:
    equal(commission_rate(9999), 0.02)
    equal(commission_rate(10000), 0.05)
    equal(commission(10000), 500)


run("commission: rate and amount", check_19)


def check_20() -> None:
    equal(earned_bonus(25000), True)
    equal(earned_bonus(24999), False)
    equal(commission_total([ord(Status.PAID, [ln(10000, 1)], 0)]), 500)


run("commission: earned_bonus and total", check_20)


def check_21() -> None:
    equal(open_value([ord(Status.PAID, [ln(500, 1)], 0)]), 500)
    equal(headline([ord(Status.PAID, [ln(500, 1)], 0)]), "1 orders, $5.00 received, $5.00 open")


run("dashboard: open_value and headline", check_21)


def check_22() -> None:
    equal(product_row(prod(1250)), "P,item,12.50,1.00")
    equal(order_row(ord(Status.PAID, [ln(1250, 1)], 0)), "1,P,Paid,12.50")


run("export: rows", check_22)


def check_23() -> None:
    equal(catalog_value(sample_products()), 67850)


run("sample: products", check_23)


def check_24() -> None:
    equal(status_label(Status.ON_HOLD), "On hold")


run("status: label", check_24)


def check_25() -> None:
    equal(is_open(Status.ON_HOLD), True)


run("status: is_open", check_25)


def check_26() -> None:
    equal(next_status(Status.ON_HOLD), Status.ON_HOLD)


run("status: next_status", check_26)


def check_27() -> None:
    equal(release(ord(Status.ON_HOLD, [ln(1, 1)], 0)), ord(Status.PAID, [ln(1, 1)], 0))
    equal(release(ord(Status.PACKED, [ln(1, 1)], 0)), ord(Status.PACKED, [ln(1, 1)], 0))


run("status: release", check_27)


def check_28() -> None:
    equal(is_revenue(Status.ON_HOLD), True)


run("status: is_revenue", check_28)


def check_29() -> None:
    equal(order_tax(ord(Status.ON_HOLD, [ln(1000, 1)], 0), [prodc(1000, Category.TOY)]), 200)


run("status: order_tax", check_29)


def check_30() -> None:
    equal(refund_share(Status.ON_HOLD), 1.0)


run("status: refund_share", check_30)


def check_31() -> None:
    equal(message_for(ord(Status.ON_HOLD, [ln(1, 1)], 0), cust("Ada", "Lovelace")), "Ada Lovelace, your order 1 is on hold")


run("status: message_for", check_31)


def check_32() -> None:
    equal(status_code(Status.ON_HOLD), "H")


run("status: status_code", check_32)


def check_33() -> None:
    equal(status_counts([ord(Status.ON_HOLD, [ln(1, 1)], 0)]), ["Draft: 0", "Paid: 0", "On hold: 1", "Packed: 0", "Shipped: 0", "Delivered: 0", "Cancelled: 0"])


run("status: status_counts", check_33)


def check_34() -> None:
    equal(can_pack(Status.ON_HOLD), False)


run("status: can_pack", check_34)


def check_35() -> None:
    equal(valid_step(Status.PAID, Status.ON_HOLD), True)
    equal(valid_step(Status.ON_HOLD, Status.PAID), True)


run("status: valid_step in and out", check_35)


def check_36() -> None:
    equal(display_name(cust("Ada", "Lovelace")), "Ada Lovelace")


run("names: display_name", check_36)


def check_37() -> None:
    equal(names(sorted_customers([cust("Zoe", "Adams"), cust("Ada", "Lovelace"), cust("Abe", "Adams")])), ["Abe Adams", "Zoe Adams", "Ada Lovelace"])


run("names: sorted_customers", check_37)


def check_38() -> None:
    equal(initials(cust("Ada", "Lovelace")), "AL")
    equal(initials(cust("mary jane", "watson")), "MW")


run("names: initials", check_38)


def check_39() -> None:
    equal(mailing_line(cust("Ada", "Lovelace")), "Ada Lovelace <a@b.org>")


run("names: mailing_line", check_39)


def check_40() -> None:
    equal(parse_customer("1,Ada,Lovelace,a@b.org,basic,Harbour"), Some(cust("Ada", "Lovelace")))
    equal(parse_customer("1,Ada Lovelace,a@b.org,basic,Harbour"), None)


run("names: parse_customer", check_40)


def check_41() -> None:
    equal(customer_row(cust("Ada", "Lovelace")), "1,Ada,Lovelace,a@b.org,basic,Harbour")


run("names: customer_row", check_41)


def check_42() -> None:
    equal(validate_customer(cust("", "Lovelace")), ["first name is empty"])
    equal(validate_customer(cust("Ada", "")), ["last name is empty"])


run("names: validate_customer", check_42)


def check_43() -> None:
    equal(message_for(ord(Status.PACKED, [ln(1, 1)], 0), cust("Ada", "Lovelace")), "Ada Lovelace, your order 1 is packed")


run("names: message_for", check_43)


def check_44() -> None:
    equal(mget(spend_by_customer([ord(Status.PAID, [ln(500, 1)], 0)], [cust("Ada", "Lovelace")]), "Ada Lovelace"), 500)


run("names: spend_by_customer", check_44)


print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
