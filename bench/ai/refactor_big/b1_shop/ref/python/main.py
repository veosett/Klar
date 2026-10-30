from analytics import revenue, top_customers
from audit import check_order
from catalog import catalog_value, price_label
from commission import commission_total
from crm import display_name, sorted_customers
from dashboard import headline, status_counts
from discount import net_amount
from export import orders_file
from fraud import needs_review
from invoice import invoice_text
from loyalty import points_for
from model import Tier
from money import fmt
from notify import message_for
from orders import grand_total, status_label
from picking import items_to_pack
from refunds import refund_note
from sample import sample_customers, sample_orders, sample_products
from shipping import shipping_label
from tax import order_tax
from warehouses import warehouses_summary
from suppliers import suppliers_summary
from carriers import carriers_summary
from campaigns import campaigns_summary
from employees import employees_summary
from routes import routes_summary
from shelves import shelves_summary
from tickets import tickets_summary
from contracts import contracts_summary
from machines import machines_summary
from branches import branches_summary
from partners import partners_summary
from assets import assets_summary
from audits import audits_summary


def main() -> None:
    """A tour of the back office with the sample data."""
    ps = sample_products()
    cs = sample_customers()
    os = sample_orders()
    print(headline(os))
    for line in status_counts(os):
        print(line)
    print(f"stock: {fmt(catalog_value(ps))}")
    for p in ps:
        print(price_label(p))
    for o in os:
        print(f"{o.id} {status_label(o.status)} {fmt(grand_total(o))} tax {fmt(order_tax(o, ps))}")
        print(f"points: {points_for(grand_total(o))}")
        print(refund_note(o))
        print("; ".join(check_order(o)))
        for c in cs:
            if c.id == o.customer:
                print(message_for(o, c))
                print(invoice_text(o, c))
                print(needs_review(o, c))
    print(", ".join(display_name(c) for c in sorted_customers(cs)))
    print(", ".join(top_customers(os, cs, 1)))
    print(fmt(revenue(os)))
    for o in os[:1]:
        print(fmt(net_amount(grand_total(o), Tier.GOLD, "TEN")))
    print(shipping_label(net_amount(0, Tier.BASIC, "")))
    print(orders_file(os))
    print(items_to_pack(os))
    print(fmt(commission_total(os)))
    print(warehouses_summary([]))
    print(suppliers_summary([]))
    print(carriers_summary([]))
    print(campaigns_summary([]))
    print(employees_summary([]))
    print(routes_summary([]))
    print(shelves_summary([]))
    print(tickets_summary([]))
    print(contracts_summary([]))
    print(machines_summary([]))
    print(branches_summary([]))
    print(partners_summary([]))
    print(assets_summary([]))
    print(audits_summary([]))


if __name__ == "__main__":
    main()
