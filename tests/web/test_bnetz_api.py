"""Tests for BNetzA-related endpoints."""

import io

class TestBnetzAPI:
    def test_list_empty(self, storage_client):
        client, _, _ = storage_client
        resp = client.get("/api/bnetz/measurements")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_upload_no_file(self, storage_client):
        client, _, _ = storage_client
        resp = client.post("/api/bnetz/upload")
        assert resp.status_code == 400

    def test_upload_not_pdf(self, storage_client):
        client, _, _ = storage_client
        data = {"file": (io.BytesIO(b"not a pdf"), "test.pdf", "application/pdf")}
        resp = client.post("/api/bnetz/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "PDF" in resp.get_json()["error"]

    def test_upload_and_list(self, storage_client, sample_bnetz_parsed):
        client, _, bnetz_st = storage_client
        # Directly insert via module storage (to avoid needing a real BNetzA PDF)
        bnetz_st.save_bnetz_measurement(sample_bnetz_parsed, b"%PDF-test")
        resp = client.get("/api/bnetz/measurements")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["provider"] == "Vodafone"

    def test_pdf_download(self, storage_client):
        client, _, bnetz_st = storage_client
        mid = bnetz_st.save_bnetz_measurement(
            {"date": "2025-01-01", "measurements_download": [], "measurements_upload": []},
            b"%PDF-download-test",
        )
        resp = client.get(f"/api/bnetz/pdf/{mid}")
        assert resp.status_code == 200
        assert resp.data == b"%PDF-download-test"
        assert resp.content_type == "application/pdf"

    def test_pdf_not_found(self, storage_client):
        client, _, _ = storage_client
        resp = client.get("/api/bnetz/pdf/9999")
        assert resp.status_code == 404

    def test_delete(self, storage_client):
        client, _, bnetz_st = storage_client
        mid = bnetz_st.save_bnetz_measurement(
            {"date": "2025-01-01", "measurements_download": [], "measurements_upload": []},
            b"%PDF-delete-test",
        )
        resp = client.delete(f"/api/bnetz/{mid}")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        # Verify deleted
        resp = client.get("/api/bnetz/measurements")
        assert resp.get_json() == []

    def test_delete_not_found(self, storage_client):
        client, _, _ = storage_client
        resp = client.delete("/api/bnetz/9999")
        assert resp.status_code == 404

