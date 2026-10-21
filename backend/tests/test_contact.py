"""Contact form API: public POST, admin-only GET."""
from __future__ import annotations

BODY = {"name": "Ravi Kumar", "phone": "+91 98765 43210",
        "email": "Ravi@Example.com", "message": "Need a Hindi voice agent"}


async def test_post_contact_saves(api_client):
    resp = await api_client.post("/api/contact", json=BODY)
    assert resp.status_code == 201, resp.text
    contact = resp.json()["contact"]
    assert contact["name"] == "Ravi Kumar"
    assert contact["email"] == "ravi@example.com"  # stored lowercased
    assert contact["created_at"]


async def test_post_contact_accepts_alias_names(api_client):
    resp = await api_client.post("/api/contact", json={
        "name": "Ana", "contact": "9998887771",
        "email": "ana@example.com", "requirement": "Outbound calls"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["contact"]["phone"] == "9998887771"
    assert resp.json()["contact"]["message"] == "Outbound calls"


async def test_post_contact_rejects_bad_email(api_client):
    resp = await api_client.post("/api/contact", json={**BODY, "email": "not-an-email"})
    assert resp.status_code == 422


async def test_get_contact_requires_admin(api_client, super_admin, normal_user):
    await api_client.post("/api/contact", json=BODY)
    assert (await api_client.get("/api/contact")).status_code == 401
    user = await api_client.get(
        "/api/contact", headers={"Authorization": f"Bearer {normal_user[0]}"})
    assert user.status_code == 403
    admin = await api_client.get(
        "/api/contact", headers={"Authorization": f"Bearer {super_admin[0]}"})
    assert admin.status_code == 200, admin.text
    assert [c["name"] for c in admin.json()["contacts"]] == ["Ravi Kumar"]
