"""
Transaction Intelligence Module - Backend API Tests
Tests for: CRUD operations, deduplication, import, export, audit logs, publish workflow
"""

import pytest
import requests
import os
import json
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = "https://data-factory-hub.preview.emergentagent.com"

# Test credentials
TEST_EMAIL = "daniel@wearebudadvisors.com"
TEST_PASSWORD = __import__("os").environ.get("SMOKE_TEST_PASSWORD", "")


class TestTransactionsAuth:
    """Authentication for transactions tests"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get authentication token"""
        response = requests.post(f"{BASE_URL}/api/v1/auth/login", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        token = response.json().get("token")
        assert token, "No token in response"
        return token
    
    @pytest.fixture(scope="class")
    def auth_headers(self, auth_token):
        """Get headers with auth token"""
        return {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json"
        }


class TestTransactionsStats(TestTransactionsAuth):
    """Test /api/v1/transactions/stats endpoint"""
    
    def test_stats_endpoint(self, auth_headers):
        """Stats endpoint returns all required metrics"""
        response = requests.get(f"{BASE_URL}/api/v1/transactions/stats", headers=auth_headers)
        assert response.status_code == 200, f"Stats failed: {response.text}"
        
        data = response.json()
        # Verify all expected fields exist
        expected_fields = [
            "total", "imported", "manual", "pending_review",
            "possible_duplicates", "duplicates_merged", "entities_matched",
            "entities_ambiguous", "sectors_pending", "ready_to_publish", "published"
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
            assert isinstance(data[field], int), f"Field {field} should be int"
        
        print(f"Stats: total={data['total']}, manual={data['manual']}, dupes={data['possible_duplicates']}")


class TestTransactionsCRUD(TestTransactionsAuth):
    """Test CRUD operations for transactions"""
    
    def test_list_transactions(self, auth_headers):
        """List transactions endpoint works"""
        response = requests.get(f"{BASE_URL}/api/v1/transactions", headers=auth_headers)
        assert response.status_code == 200, f"List failed: {response.text}"
        
        data = response.json()
        assert "transactions" in data
        assert "total" in data
        assert isinstance(data["transactions"], list)
        print(f"Found {data['total']} transactions")
    
    def test_list_transactions_with_search(self, auth_headers):
        """Search filter works"""
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions",
            params={"search": "Acme"},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        print(f"Search 'Acme' returned {data['total']} results")
    
    def test_create_transaction(self, auth_headers):
        """Create a new manual transaction"""
        payload = {
            "target_name": "TEST_TechCorp SL",
            "buyer_name": "TEST_BigBuyer Inc",
            "seller_name": "TEST_FounderGroup",
            "announcement_date": "2026-01-15",
            "status": "completed",
            "transaction_type": "takeover",
            "buyer_type": "strategic",
            "geography_primary": "Spain",
            "value_eurm": 25.5,
            "value_disclosed": True,
            "sector_original": "Technology",
            "source": "Test Source",
            "source_url": "https://example.com/test",
            "observations": "Test transaction for automated testing",
            "confidence_level": "high"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/v1/transactions",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 200, f"Create failed: {response.text}"
        
        data = response.json()
        assert "transaction_id" in data
        assert data["target_name"] == "TEST_TechCorp SL"
        assert data["buyer_name"] == "TEST_BigBuyer Inc"
        assert data["source_type"] == "manual"
        assert data["dedupe_status"] in ["pending_check", "unique", "possible_duplicate"]
        
        # Store for later tests
        TestTransactionsCRUD.created_tx_id = data["transaction_id"]
        print(f"Created transaction: {data['transaction_id']}")
        return data["transaction_id"]
    
    def test_get_transaction_detail(self, auth_headers):
        """Get single transaction by ID"""
        tx_id = getattr(TestTransactionsCRUD, 'created_tx_id', None)
        if not tx_id:
            pytest.skip("No transaction created in previous test")
        
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/{tx_id}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get detail failed: {response.text}"
        
        data = response.json()
        assert data["transaction_id"] == tx_id
        assert data["target_name"] == "TEST_TechCorp SL"
        assert "company_links" in data
        assert "dedupe_candidates" in data
        print(f"Got transaction detail: {data['target_name']}")
    
    def test_update_transaction(self, auth_headers):
        """Update an existing transaction"""
        tx_id = getattr(TestTransactionsCRUD, 'created_tx_id', None)
        if not tx_id:
            pytest.skip("No transaction created in previous test")
        
        update_payload = {
            "value_eurm": 30.0,
            "observations": "Updated observation for testing"
        }
        
        response = requests.put(
            f"{BASE_URL}/api/v1/transactions/{tx_id}",
            json=update_payload,
            headers=auth_headers
        )
        assert response.status_code == 200, f"Update failed: {response.text}"
        
        data = response.json()
        assert data["value_eurm"] == 30.0
        assert data["observations"] == "Updated observation for testing"
        print(f"Updated transaction: value_eurm={data['value_eurm']}")
    
    def test_review_transaction(self, auth_headers):
        """Set review status on transaction"""
        tx_id = getattr(TestTransactionsCRUD, 'created_tx_id', None)
        if not tx_id:
            pytest.skip("No transaction created in previous test")
        
        response = requests.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/review",
            params={"status": "approved"},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Review failed: {response.text}"
        
        data = response.json()
        assert data["status"] == "approved"
        print("Transaction approved")
    
    def test_sector_mapping(self, auth_headers):
        """Set sector mapping on transaction"""
        tx_id = getattr(TestTransactionsCRUD, 'created_tx_id', None)
        if not tx_id:
            pytest.skip("No transaction created in previous test")
        
        response = requests.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/sector-mapping",
            params={"cis_category": "Digital Growth", "status": "approved"},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Sector mapping failed: {response.text}"
        print("Sector mapping set")
    
    def test_validate_publish(self, auth_headers):
        """Validate transaction for publishing"""
        tx_id = getattr(TestTransactionsCRUD, 'created_tx_id', None)
        if not tx_id:
            pytest.skip("No transaction created in previous test")
        
        response = requests.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/validate-publish",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Validate publish failed: {response.text}"
        
        data = response.json()
        # May or may not be valid depending on dedupe status
        print(f"Validate publish result: valid={data.get('valid')}, errors={data.get('errors', [])}")


class TestTransactionsDeduplication(TestTransactionsAuth):
    """Test deduplication endpoints"""
    
    def test_list_dedupe_candidates(self, auth_headers):
        """List duplicate candidates"""
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/dedupe/candidates",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Dedupe list failed: {response.text}"
        
        data = response.json()
        assert "candidates" in data
        assert "total" in data
        
        if data["candidates"]:
            cand = data["candidates"][0]
            assert "candidate_id" in cand
            assert "similarity_score" in cand
            assert "recommendation" in cand
            assert "tx_a" in cand
            assert "tx_b" in cand
            print(f"Found {len(data['candidates'])} dedupe candidates")
        else:
            print("No dedupe candidates found")
    
    def test_keep_separate(self, auth_headers):
        """Test keeping duplicates separate"""
        # First get candidates
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/dedupe/candidates",
            headers=auth_headers
        )
        data = response.json()
        
        if not data["candidates"]:
            pytest.skip("No dedupe candidates to test")
        
        candidate_id = data["candidates"][0]["candidate_id"]
        
        response = requests.post(
            f"{BASE_URL}/api/v1/transactions/dedupe/{candidate_id}/keep-separate",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Keep separate failed: {response.text}"
        
        result = response.json()
        assert result["status"] == "kept_separate"
        print(f"Kept candidate {candidate_id} separate")


class TestTransactionsImportExport(TestTransactionsAuth):
    """Test import and export functionality"""
    
    def test_list_imports(self, auth_headers):
        """List import history"""
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/imports/list",
            headers=auth_headers
        )
        assert response.status_code == 200, f"List imports failed: {response.text}"
        
        data = response.json()
        assert "imports" in data
        print(f"Found {len(data['imports'])} imports")
    
    def test_export_json(self, auth_headers):
        """Export transactions as JSON"""
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/export",
            params={"format": "json"},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Export JSON failed: {response.text}"
        
        # Should be valid JSON
        data = response.json()
        assert isinstance(data, list)
        print(f"Exported {len(data)} transactions as JSON")
    
    def test_export_excel(self, auth_headers):
        """Export transactions as Excel"""
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/export",
            params={"format": "excel"},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Export Excel failed: {response.text}"
        
        # Should have Excel content type
        content_type = response.headers.get("content-type", "")
        assert "spreadsheet" in content_type or "octet-stream" in content_type
        assert len(response.content) > 0
        print(f"Exported Excel file: {len(response.content)} bytes")


class TestTransactionsSectors(TestTransactionsAuth):
    """Test sector mapping endpoints"""
    
    def test_list_sector_mappings(self, auth_headers):
        """List sector mappings"""
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/sectors/mappings",
            headers=auth_headers
        )
        assert response.status_code == 200, f"List sectors failed: {response.text}"
        
        data = response.json()
        assert "sectors" in data
        
        if data["sectors"]:
            sector = data["sectors"][0]
            assert "sector_original" in sector
            assert "count" in sector
            print(f"Found {len(data['sectors'])} unique sectors")
        else:
            print("No sectors found")


class TestTransactionsAudit(TestTransactionsAuth):
    """Test audit log endpoints"""
    
    def test_global_audit_log(self, auth_headers):
        """Get global audit log"""
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/audit-global",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Global audit failed: {response.text}"
        
        data = response.json()
        assert "logs" in data
        assert "total" in data
        
        if data["logs"]:
            log = data["logs"][0]
            assert "action" in log
            assert "changed_by" in log
            assert "changed_at" in log
            print(f"Found {data['total']} audit log entries")
        else:
            print("No audit logs found")
    
    def test_transaction_audit_log(self, auth_headers):
        """Get audit log for specific transaction"""
        tx_id = getattr(TestTransactionsCRUD, 'created_tx_id', None)
        if not tx_id:
            # Get any transaction
            response = requests.get(
                f"{BASE_URL}/api/v1/transactions",
                params={"limit": 1},
                headers=auth_headers
            )
            if response.status_code == 200 and response.json()["transactions"]:
                tx_id = response.json()["transactions"][0]["transaction_id"]
            else:
                pytest.skip("No transactions available")
        
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/audit/{tx_id}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Transaction audit failed: {response.text}"
        
        data = response.json()
        assert "logs" in data
        print(f"Found {len(data['logs'])} audit entries for {tx_id}")


class TestTransactionsCleanup(TestTransactionsAuth):
    """Cleanup test data"""
    
    def test_delete_test_transaction(self, auth_headers):
        """Delete the test transaction created earlier"""
        tx_id = getattr(TestTransactionsCRUD, 'created_tx_id', None)
        if not tx_id:
            pytest.skip("No transaction to delete")
        
        response = requests.delete(
            f"{BASE_URL}/api/v1/transactions/{tx_id}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Delete failed: {response.text}"
        
        data = response.json()
        assert data["status"] == "deleted"
        print(f"Deleted test transaction: {tx_id}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
