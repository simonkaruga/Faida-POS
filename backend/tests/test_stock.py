"""Phase 4: stock. Done when selling a tot, a bottle and a dish all reduce stock
correctly (masterplan 11)."""

from decimal import Decimal

import pytest
from conftest import login
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

SAM, JANE = "8642", "1357"


@pytest.fixture
def people(add_staff):
    add_staff("Sam", "supervisor", SAM)
    add_staff("Jane", "waiter", JANE)


@pytest.fixture
def opts(client, owner, menu):
    out = {}
    for cat in client.get("/api/menu", headers=owner).json()["categories"]:
        for item in cat["items"]:
            for o in item["options"]:
                out[f"{item['name']} - {o['label']}" if o["label"] else item["name"]] = o["id"]
    return out


def stock(client, headers):
    return {s["name"]: s for s in client.get("/api/stock", headers=headers).json()}


def deliver(client, headers, item_id, packs=0, units=0, cost=None):
    r = client.post("/api/stock/deliveries", headers=headers,
                    json={"lines": [{"stock_item_id": item_id, "packs": packs, "units": units, "cost": cost}]})
    assert r.status_code == 201, r.text
    return r.json()


def sell(client, headers, *items, tab="Kamau"):
    bill = client.post("/api/bills", json={"tab_name": tab}, headers=headers).json()
    r = client.post(f"/api/bills/{bill['id']}/send", headers=headers,
                    json={"items": [{"sell_option_id": o, "quantity": q} for o, q in items]})
    assert r.status_code == 200, r.text
    return r.json()


def level(client, headers, name):
    return Decimal(stock(client, headers)[name]["level"])


def test_selling_a_tot_a_bottle_and_a_dish_reduces_stock(client, owner, opts):
    s = stock(client, owner)
    deliver(client, owner, s["Johnnie Walker Red 750ml"]["id"], units=3)  # 2,250 ml
    deliver(client, owner, s["Chicken (quarter)"]["id"], units=10)
    deliver(client, owner, s["Potatoes"]["id"], units=5)  # kg
    deliver(client, owner, s["Cooking oil"]["id"], units=2)  # litres
    deliver(client, owner, s["Tusker 500ml"]["id"], packs=1)  # a crate of 25

    sell(client, owner, (opts["Johnnie Walker Red - Single tot"], 2), (opts["Johnnie Walker Red - Double"], 1),
         (opts["Johnnie Walker Red - Bottle"], 1), (opts["Chicken & chips"], 2), (opts["Tusker"], 3))

    after = stock(client, owner)
    assert Decimal(after["Johnnie Walker Red 750ml"]["level"]) == 2250 - 2 * 25 - 50 - 750  # 1,400 ml
    assert after["Johnnie Walker Red 750ml"]["level_text"] == "1.9 bottles ≈ 56 tots"
    assert Decimal(after["Chicken (quarter)"]["level"]) == 8
    assert Decimal(after["Potatoes"]["level"]) == 5000 - 600
    assert Decimal(after["Cooking oil"]["level"]) == 2000 - 80
    assert Decimal(after["Tusker 500ml"]["level"]) == 22


def test_a_sale_is_never_blocked_by_stock(client, owner, opts):
    bill = sell(client, owner, (opts["Guinness"], 2))
    assert bill["total"] == 640
    guinness = stock(client, owner)["Guinness 500ml"]
    assert Decimal(guinness["level"]) == -2 and guinness["check"] is True


def test_void_not_prepared_returns_already_poured_is_waste(client, owner, opts):
    s = stock(client, owner)
    deliver(client, owner, s["Tusker 500ml"]["id"], units=10)
    bill = sell(client, owner, (opts["Tusker"], 2))
    first, second = [l["id"] for l in bill["lines"]]
    client.post(f"/api/bills/{bill['id']}/lines/{first}/void", json={"reason": "not_prepared"}, headers=owner)
    assert level(client, owner, "Tusker 500ml") == 9
    client.post(f"/api/bills/{bill['id']}/lines/{second}/void", json={"reason": "already_prepared"}, headers=owner)
    assert level(client, owner, "Tusker 500ml") == 9
    kinds = [m["kind"] for m in client.get(f"/api/stock/items/{s['Tusker 500ml']['id']}/movements", headers=owner).json()]
    assert kinds == ["waste", "sale_return", "sale_return", "sale", "sale", "delivery"]


def test_cancelled_bill_returns_stock(client, owner, opts):
    s = stock(client, owner)
    deliver(client, owner, s["Coke 500ml"]["id"], units=10)
    bill = sell(client, owner, (opts["Coke"], 4))
    client.post(f"/api/bills/{bill['id']}/payments", json={"method": "cash", "amount": 400}, headers=owner)
    r = client.post(f"/api/bills/{bill['id']}/cancel", json={"reason": "not_prepared"}, headers=owner)
    assert r.status_code == 200
    assert level(client, owner, "Coke 500ml") == 10


def test_deliveries_by_crate_set_the_buying_price(client, owner, people, menu):
    sam = login(client, SAM)
    tusker = stock(client, owner)["Tusker 500ml"]
    r = deliver(client, sam, tusker["id"], packs=2, units=5, cost=11275)
    assert r["lines"] == ["Tusker 500ml: +55 bottles"]
    mine = stock(client, owner)["Tusker 500ml"]
    assert Decimal(mine["level"]) == 55 and Decimal(mine["buying_price"]) == 205 and mine["value"] == 11275
    # Supervisors receive stock but don't see buying prices or stock value.
    theirs = stock(client, sam)["Tusker 500ml"]
    assert theirs["buying_price"] is None and theirs["value"] is None
    chicken = stock(client, owner)["Chicken (quarter)"]
    r = client.post("/api/stock/deliveries", headers=sam, json={"lines": [{"stock_item_id": chicken["id"], "packs": 1}]})
    assert r.status_code == 422
    assert client.get("/api/stock", headers=login(client, JANE)).status_code == 403


def test_stock_take_shows_variance_in_units_and_shillings(client, owner, people, menu):
    jw = stock(client, owner)["Johnnie Walker Red 750ml"]
    deliver(client, owner, jw["id"], units=3)
    body = {"note": "Monday count", "counts": [{"stock_item_id": jw["id"], "full": 2, "open_tenths": 4}]}
    r = client.post("/api/stock/takes", json=body, headers=owner)
    assert r.status_code == 201
    (line,) = r.json()["lines"]
    # 2,250 ml expected, 1,800 counted: 450 ml = 0.6 bottle = 18 tots = 0.6 x 2,400.
    assert line["message"] == "Missing 0.6 bottles ≈ 18 tots ≈ KSh 1,440"
    assert line["value"] == -1440 and r.json()["total_value"] == -1440
    assert level(client, owner, "Johnnie Walker Red 750ml") == 1800

    sam = login(client, SAM)
    r = client.post("/api/stock/takes", headers=sam, json={"counts": [{"stock_item_id": jw["id"], "full": 2}]})
    (line,) = r.json()["lines"]
    assert line["message"] == "Missing 0.4 bottles ≈ 12 tots" and line["value"] is None

    tusker = stock(client, owner)["Tusker 500ml"]
    r = client.post("/api/stock/takes", headers=sam, json={"counts": [{"stock_item_id": tusker["id"], "full": 3, "open_tenths": 5}]})
    assert r.status_code == 422


def test_waste_needs_approval_for_a_waiter(client, owner, people, menu):
    jane, sam = login(client, JANE), login(client, SAM)
    gin = stock(client, owner)["Gilbey's Gin 750ml"]
    deliver(client, owner, gin["id"], units=2)
    body = {"stock_item_id": gin["id"], "quantity": 1, "reason": "Broken bottle"}
    assert client.post("/api/stock/waste", json=body, headers=jane).status_code == 403
    approval = client.post("/api/auth/approvals", headers=jane,
                           json={"action": "record_waste", "approver_pin": SAM, "reason": "Broken bottle"}).json()["id"]
    assert client.post("/api/stock/waste", json={**body, "approval_id": approval}, headers=jane).status_code == 201
    r = client.post("/api/stock/waste", json={"stock_item_id": gin["id"], "tots": 2, "reason": "Spilt"}, headers=sam)
    assert r.status_code == 201 and Decimal(r.json()["level"]) == 750 - 50


def test_low_stock_alert_at_reorder_level(client, owner, opts):
    coke = stock(client, owner)["Coke 500ml"]  # reorder level: 24 bottles
    deliver(client, owner, coke["id"], units=30)
    assert stock(client, owner)["Coke 500ml"]["low"] is False
    sell(client, owner, (opts["Coke"], 6))
    assert stock(client, owner)["Coke 500ml"]["low"] is True


def test_owner_sets_recipes(client, owner, people, opts):
    sam = login(client, SAM)
    assert client.get("/api/stock/recipes", headers=sam).status_code == 403
    recipes = {f"{r['item_name']} {r['option_label']}".strip(): r for r in client.get("/api/stock/recipes", headers=owner).json()}
    assert recipes["Johnnie Walker Red Single tot"]["lines"][0]["text"] == "1 tot"
    assert [l["stock_item"] for l in recipes["Chicken & chips"]["lines"]] == ["Chicken (quarter)", "Potatoes", "Cooking oil"]

    s = stock(client, owner)
    smokie = recipes["Smokie"]["sell_option_id"]
    r = client.put(f"/api/stock/recipes/{smokie}", headers=owner,
                   json={"lines": [{"stock_item_id": s["Smokie"]["id"], "quantity": 2}]})
    assert r.status_code == 200 and r.json()["lines"][0]["text"] == "2 pcs"
    deliver(client, owner, s["Smokie"]["id"], units=10)
    sell(client, owner, (opts["Smokie"], 1))
    assert level(client, owner, "Smokie") == 8
    bad = client.put(f"/api/stock/recipes/{smokie}", headers=owner,
                     json={"lines": [{"stock_item_id": s["Smokie"]["id"], "quantity": 1, "in_tots": True}]})
    assert bad.status_code == 409


def test_new_stock_item_and_price_per_counting_unit(client, owner, menu):
    r = client.post("/api/stock/items", headers=owner, json={
        "name": "Captain Morgan 250ml", "station": "bar", "unit": "ml", "bottle_size": 250,
        "pack_name": "carton", "pack_size": 24, "buying_price": 600, "reorder_level": 6})
    assert r.status_code == 201
    item = r.json()
    assert Decimal(item["buying_price"]) == 600 and item["counting_unit"] == "bottle"
    assert Decimal(item["reorder_level"]) == 1500
    r = client.patch(f"/api/stock/items/{item['id']}", json={"buying_price": 650}, headers=owner)
    assert Decimal(r.json()["buying_price"]) == 650


def test_new_stock_item_goes_on_the_menu_with_its_selling_price(client, owner, menu):
    """One form: the stock item, the menu item and what each sale takes from stock."""
    category = client.get("/api/menu/manage", headers=owner).json()["categories"][0]["id"]
    r = client.post("/api/stock/items", headers=owner, json={
        "name": "Captain Morgan 250ml", "station": "bar", "unit": "ml", "bottle_size": 250, "buying_price": 600,
        "sell": {"category_id": category, "price": 900, "tot_price": 120}})
    assert r.status_code == 201, r.text
    item = r.json()
    assert [(s["name"], s["price"]) for s in item["selling"]] == [
        ("Captain Morgan 250ml · Single tot", 120), ("Captain Morgan 250ml · Bottle", 900)]
    deliver(client, owner, item["id"], units=2)  # 500 ml
    tot, bottle = (s["option_id"] for s in item["selling"])
    sell(client, owner, (tot, 1), (bottle, 1))
    assert level(client, owner, "Captain Morgan 250ml") == 500 - 25 - 250  # sample tot is 25 ml
    assert [s["price"] for s in stock(client, owner)["Captain Morgan 250ml"]["selling"]] == [120, 900]

    beer = client.post("/api/stock/items", headers=owner, json={
        "name": "Hunter's Gold", "station": "bar", "unit": "bottle", "buying_price": 180,
        "sell": {"category_id": category, "price": 250}}).json()
    assert [(s["name"], s["price"]) for s in beer["selling"]] == [("Hunter's Gold", 250)]
    r = client.post("/api/stock/items", headers=owner, json={
        "name": "Sugar", "station": "kitchen", "unit": "g", "sell": {"category_id": category, "tot_price": 10}})
    assert r.status_code == 422  # only a spirit sells by the tot


def test_stock_movements_are_permanent(client, owner, db, menu):
    deliver(client, owner, stock(client, owner)["Coke 500ml"]["id"], units=1)
    with db.bind.connect() as conn, pytest.raises(ProgrammingError, match="permanent"):
        conn.execute(text("UPDATE stock_movements SET quantity = 100"))


def test_load_stock_onto_an_existing_menu(client, owner, db, business):
    import json

    from conftest import SAMPLE_MENU

    from app.menu.importer import load_menu, load_stock

    with open(SAMPLE_MENU, encoding="utf-8") as f:
        data = json.load(f)
    no_stock = [{**c, "items": [{**i, "uses": [], "modifier_groups": [],
                                 "options": [{**o, "uses": []} for o in i["options"]] if "options" in i else None}
                                for i in c["items"]]} for c in data["categories"]]
    load_menu(db, business.id, {**data, "stock": [], "tot_size_ml": None, "modifier_groups": [], "categories": no_stock, "price_rules": []})
    assert client.get("/api/stock", headers=owner).json() == []
    counts = load_stock(db, business.id, data)
    assert counts == {"stock_items": 24, "recipes": 25}
    assert load_stock(db, business.id, data) == {"stock_items": 0, "recipes": 0}
