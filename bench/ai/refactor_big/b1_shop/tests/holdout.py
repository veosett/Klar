import sys
from typing import Any, Callable

from model import Category, Customer, Line, Order, Product, Status, Tier
from analytics import big_orders, daily_revenue, orders_over, revenue, top_customers
from audit import check_order, valid_step
from catalog import catalog_value, is_gift, stock_value, within_budget
from commission import commission_rate
from crm import customer_header, find_by_name, greeting, same_person
from dashboard import status_color, value_alert
from discount import coupon_value, volume_rate
from export import order_row
from fraud import is_reviewable, needs_review
from invoice import header, line_text
from loyalty import tier_after, to_next_point
from notify import reminder
from orders import advance, can_cancel, hold
from picking import packing_queue
from refunds import refund_amount, refund_note, return_fee
from sample import sample_customers, sample_orders
from shipping import member_cost, shipping_label
from tax import line_tax, tax_note, taxable


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
    equal(is_gift(prod(2499)), True)
    equal(is_gift(prod(2500)), False)


run("catalog: is_gift", check_0)


def check_1() -> None:
    equal(stock_value(prod(1250)), 2500)
    equal(catalog_value([prod(100), prod(200)]), 600)


run("catalog: stock values", check_1)


def check_2() -> None:
    equal(size(within_budget([prod(100), prod(200)], 150)), 1)


run("catalog: within_budget", check_2)


def check_3() -> None:
    equal(line_tax(ln(125, 1), [prodc(125, Category.GARDEN)]), 13)


run("tax: line_tax rounds half up", check_3)


def check_4() -> None:
    equal(tax_note(0), "tax free")
    equal(tax_note(1250), "tax $12.50")


run("tax: tax_note", check_4)


def check_5() -> None:
    equal(volume_rate(19999), 0.0)
    equal(volume_rate(20000), 0.05)
    equal(volume_rate(49999), 0.05)
    equal(volume_rate(50000), 0.1)


run("discount: volume_rate", check_5)


def check_6() -> None:
    equal(coupon_value("TEN", 5000), 1000)
    equal(coupon_value("FIVE", 300), 300)
    equal(coupon_value("NONE", 300), 0)


run("discount: coupon_value", check_6)


def check_7() -> None:
    equal(member_cost(501, Tier.GOLD), 251)
    equal(member_cost(501, Tier.BASIC), 501)


run("shipping: member_cost", check_7)


def check_8() -> None:
    equal(shipping_label(0), "free shipping")
    equal(shipping_label(499), "shipping $4.99")


run("shipping: shipping_label", check_8)


def check_9() -> None:
    equal(tier_after(29999), Tier.BASIC)
    equal(tier_after(30000), Tier.SILVER)
    equal(tier_after(100000), Tier.GOLD)


run("loyalty: tier_after", check_9)


def check_10() -> None:
    equal(to_next_point(2599), 401)


run("loyalty: to_next_point", check_10)


def check_11() -> None:
    equal(needs_review(ord(Status.PAID, [ln(100000, 1)], 0), custt(Tier.GOLD)), True)
    equal(needs_review(ord(Status.PAID, [ln(99999, 1)], 0), custt(Tier.GOLD)), False)


run("fraud: needs_review", check_11)


def check_12() -> None:
    equal(refund_note(ord(Status.SHIPPED, [ln(1000, 1)], 0)), "Refund $9.50 for order 1")


run("refunds: refund_note", check_12)


def check_13() -> None:
    equal(return_fee(1999), 350)
    equal(return_fee(2000), 0)


run("refunds: return_fee", check_13)


def check_14() -> None:
    equal(line_text(ln(1250, 2)), "  2 x S @ $12.50 = $25.00")


run("invoice: line_text", check_14)


def check_15() -> None:
    equal(big_orders([ord(Status.PAID, [ln(100000, 1)], 0), ord(Status.PAID, [ln(99999, 1)], 0)]), 1)


run("analytics: big_orders", check_15)


def check_16() -> None:
    equal(size(orders_over([ord(Status.PAID, [ln(500, 1)], 0)], 500)), 1)
    equal(daily_revenue([ord(Status.PAID, [ln(500, 1)], 0)], 1), 500)


run("analytics: orders_over and daily_revenue", check_16)


def check_17() -> None:
    equal(commission_rate(99999), 0.05)
    equal(commission_rate(100000), 0.08)


run("commission: top rate", check_17)


def check_18() -> None:
    equal(value_alert([ord(Status.PAID, [ln(500001, 1)], 0)]), True)
    equal(value_alert([ord(Status.PAID, [ln(500000, 1)], 0)]), False)


run("dashboard: value_alert", check_18)


def check_19() -> None:
    equal(check_order(ord(Status.PAID, [ln(0, 1)], 0)), ["bad price"])
    equal(size(check_order(ord(Status.PAID, [ln(1, 1)], 0))), 0)


run("audit: check_order", check_19)


def check_20() -> None:
    equal(revenue(sample_orders()), 21599)


run("sample: orders", check_20)


def check_21() -> None:
    equal(can_cancel(Status.ON_HOLD), True)


run("status: can_cancel", check_21)


def check_22() -> None:
    equal(hold(ord(Status.PAID, [ln(1, 1)], 0)), ord(Status.ON_HOLD, [ln(1, 1)], 0))
    equal(hold(ord(Status.DRAFT, [ln(1, 1)], 0)), ord(Status.DRAFT, [ln(1, 1)], 0))


run("status: hold", check_22)


def check_23() -> None:
    equal(advance(ord(Status.ON_HOLD, [ln(1, 1)], 0)), ord(Status.ON_HOLD, [ln(1, 1)], 0))


run("status: advance", check_23)


def check_24() -> None:
    equal(taxable(Status.ON_HOLD), True)


run("status: taxable", check_24)


def check_25() -> None:
    equal(is_reviewable(Status.ON_HOLD), True)


run("status: is_reviewable", check_25)


def check_26() -> None:
    equal(refund_amount(ord(Status.ON_HOLD, [ln(1000, 1)], 0)), 1000)


run("status: refund_amount", check_26)


def check_27() -> None:
    equal(status_color(Status.ON_HOLD), "amber")


run("status: status_color", check_27)


def check_28() -> None:
    equal(order_row(ord(Status.ON_HOLD, [ln(1250, 1)], 0)), "1,H,On hold,12.50")


run("status: order_row", check_28)


def check_29() -> None:
    equal(size(packing_queue([ord(Status.ON_HOLD, [ln(1, 1)], 0)])), 0)


run("status: packing_queue", check_29)


def check_30() -> None:
    equal(valid_step(Status.ON_HOLD, Status.PACKED), False)
    equal(valid_step(Status.ON_HOLD, Status.CANCELLED), True)


run("status: valid_step onwards", check_30)


def check_31() -> None:
    equal(revenue([ord(Status.ON_HOLD, [ln(500, 1)], 0)]), 500)


run("status: revenue", check_31)


def check_32() -> None:
    equal(names(find_by_name([cust("Ada", "Lovelace"), cust("Lovelace", "Byron"), cust("Alan", "Turing")], "LOVE")), ["Ada Lovelace", "Lovelace Byron"])


run("names: find_by_name", check_32)


def check_33() -> None:
    equal(greeting(cust("Ada", "Lovelace")), "Dear Ada Lovelace")


run("names: greeting", check_33)


def check_34() -> None:
    equal(customer_header(), "id,first_name,last_name,email,tier,city")


run("names: customer_header", check_34)


def check_35() -> None:
    equal(same_person(cust("ADA", "Lovelace"), cust("ada", "LOVELACE")), True)
    equal(same_person(cust("Ada", "Lovelace"), cust("Ada", "Byron")), False)


run("names: same_person", check_35)


def check_36() -> None:
    equal(header(ord(Status.PAID, [ln(1, 1)], 0), cust("Ada", "Lovelace")), "Invoice 1 for Ada Lovelace, Harbour")


run("names: invoice header", check_36)


def check_37() -> None:
    equal(reminder(cust("Ada", "Lovelace"), 500), "Ada Lovelace: please pay $5.00")


run("names: reminder", check_37)


def check_38() -> None:
    equal(top_customers([ord(Status.PAID, [ln(500, 1)], 0)], [cust("Ada", "Lovelace")], 1), ["Ada Lovelace"])


run("names: top_customers", check_38)


def check_39() -> None:
    equal(names(sample_customers()), ["Ada Lovelace", "Alan Turing"])


run("names: sample customers", check_39)


print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
