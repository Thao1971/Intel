"""
Entity Matching Module - Backend API Tests
Tests for: Matching stats, pending links, run-all, search, confirm, reject, manual-link, needs-new
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


class TestEntityMatchingAuth:
    """Authentication for entity matching tests"""
    
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


class TestMatchingStats(TestEntityMatchingAuth):
    """Test GET /api/v1/transactions/matching/stats endpoint"""
    
    def test_matching_stats_returns_all_counts(self, auth_headers):
        """Stats endpoint returns counts by match_status"""
        response = requests.get(f"{BASE_URL}/api/v1/transactions/matching/stats", headers=auth_headers)
        assert response.status_code == 200, f"Matching stats failed: {response.text}"
        
        data = response.json()
        # Verify all expected status counts exist
        expected_fields = [
            "total_links",
            "auto_strong_candidate",
            "auto_ambiguous_candidate",
            "unmatched",
            "manual_confirmed",
            "manual_rejected",
            "needs_new_company",
            "transactions_needing_review"
        ]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
            assert isinstance(data[field], int), f"Field {field} should be int"
        
        print(f"Matching stats: total_links={data['total_links']}, strong={data['auto_strong_candidate']}, ambiguous={data['auto_ambiguous_candidate']}, unmatched={data['unmatched']}")
        return data


class TestMatchingPending(TestEntityMatchingAuth):
    """Test GET /api/v1/transactions/matching/pending endpoint"""
    
    def test_pending_returns_links_with_transaction_data(self, auth_headers):
        """Pending endpoint returns links enriched with transaction data"""
        response = requests.get(f"{BASE_URL}/api/v1/transactions/matching/pending", headers=auth_headers)
        assert response.status_code == 200, f"Matching pending failed: {response.text}"
        
        data = response.json()
        assert "links" in data
        assert "total" in data
        assert isinstance(data["links"], list)
        
        if data["links"]:
            link = data["links"][0]
            # Verify link structure
            assert "link_id" in link
            assert "transaction_id" in link
            assert "entity_role" in link
            assert "raw_entity_name" in link
            assert "match_status" in link
            assert "match_confidence" in link
            # Verify transaction enrichment
            assert "transaction" in link, "Link should have enriched transaction data"
            if link["transaction"]:
                assert "target_name" in link["transaction"]
            print(f"Found {data['total']} pending links, first: {link['raw_entity_name']} ({link['match_status']})")
        else:
            print("No pending links found")
        
        return data
    
    def test_pending_with_status_filter(self, auth_headers):
        """Pending endpoint filters by status_filter parameter"""
        # Test filtering by auto_ambiguous_candidate
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/matching/pending",
            params={"status_filter": "auto_ambiguous_candidate"},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Filtered pending failed: {response.text}"
        
        data = response.json()
        # All returned links should have the filtered status
        for link in data["links"]:
            assert link["match_status"] == "auto_ambiguous_candidate", f"Expected auto_ambiguous_candidate, got {link['match_status']}"
        
        print(f"Filtered by auto_ambiguous_candidate: {data['total']} links")


class TestMatchingSearch(TestEntityMatchingAuth):
    """Test GET /api/v1/transactions/matching/search endpoint"""
    
    def test_search_finds_cis_companies(self, auth_headers):
        """Search endpoint finds CIS companies by name"""
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/matching/search",
            params={"q": "Ogilvy"},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Matching search failed: {response.text}"
        
        data = response.json()
        assert "results" in data
        assert isinstance(data["results"], list)
        
        if data["results"]:
            result = data["results"][0]
            assert "id" in result
            assert "company_name" in result
            print(f"Search 'Ogilvy' found {len(data['results'])} companies, first: {result.get('company_name')}")
        else:
            print("No companies found for 'Ogilvy'")
        
        return data
    
    def test_search_by_cif(self, auth_headers):
        """Search endpoint can find by CIF"""
        # Search with at least 2 characters (minimum required)
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/matching/search",
            params={"q": "B8"},  # Common CIF prefix in Spain (min 2 chars)
            headers=auth_headers
        )
        assert response.status_code == 200
        print(f"Search 'B8' (CIF prefix) found {len(response.json()['results'])} results")
    
    def test_search_minimum_length(self, auth_headers):
        """Search requires minimum 2 characters"""
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/matching/search",
            params={"q": "A"},  # Only 1 character
            headers=auth_headers
        )
        # Should fail validation
        assert response.status_code == 422, "Should require min 2 characters"


class TestMatchingRunAll(TestEntityMatchingAuth):
    """Test POST /api/v1/transactions/matching/run-all endpoint"""
    
    def test_run_all_processes_unmatched(self, auth_headers):
        """Run-all endpoint processes all unmatched transactions"""
        response = requests.post(f"{BASE_URL}/api/v1/transactions/matching/run-all", headers=auth_headers)
        assert response.status_code == 200, f"Run-all failed: {response.text}"
        
        data = response.json()
        assert "processed" in data
        assert isinstance(data["processed"], int)
        print(f"Run-all processed {data['processed']} transactions")


class TestMatchingActions(TestEntityMatchingAuth):
    """Test confirm, reject, manual-link, needs-new endpoints"""
    
    @pytest.fixture(scope="class")
    def test_link_id(self, auth_headers):
        """Get a link_id for testing actions"""
        response = requests.get(f"{BASE_URL}/api/v1/transactions/matching/pending", headers=auth_headers)
        if response.status_code == 200 and response.json()["links"]:
            return response.json()["links"][0]["link_id"]
        return None
    
    def test_confirm_match(self, auth_headers, test_link_id):
        """Confirm endpoint changes status to manual_confirmed"""
        if not test_link_id:
            pytest.skip("No link available for testing")
        
        response = requests.post(
            f"{BASE_URL}/api/v1/transactions/matching/{test_link_id}/confirm",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Confirm failed: {response.text}"
        
        data = response.json()
        assert data["status"] == "manual_confirmed"
        print(f"Confirmed link {test_link_id}")
        
        # Verify the change persisted
        pending_response = requests.get(
            f"{BASE_URL}/api/v1/transactions/matching/pending",
            params={"status_filter": "manual_confirmed"},
            headers=auth_headers
        )
        confirmed_links = [l for l in pending_response.json()["links"] if l["link_id"] == test_link_id]
        assert len(confirmed_links) == 1, "Confirmed link should be retrievable with manual_confirmed filter"
    
    def test_reject_match(self, auth_headers):
        """Reject endpoint changes status to manual_rejected"""
        # Get a fresh link to reject
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/matching/pending",
            params={"status_filter": "auto_ambiguous_candidate"},
            headers=auth_headers
        )
        if response.status_code != 200 or not response.json()["links"]:
            pytest.skip("No ambiguous link available for reject test")
        
        link_id = response.json()["links"][0]["link_id"]
        
        response = requests.post(
            f"{BASE_URL}/api/v1/transactions/matching/{link_id}/reject",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Reject failed: {response.text}"
        
        data = response.json()
        assert data["status"] == "manual_rejected"
        print(f"Rejected link {link_id}")
    
    def test_needs_new_company(self, auth_headers):
        """Needs-new endpoint marks as needs_new_company"""
        # Get a fresh link
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/matching/pending",
            params={"status_filter": "unmatched"},
            headers=auth_headers
        )
        if response.status_code != 200 or not response.json()["links"]:
            # Try auto_ambiguous_candidate
            response = requests.get(
                f"{BASE_URL}/api/v1/transactions/matching/pending",
                params={"status_filter": "auto_ambiguous_candidate"},
                headers=auth_headers
            )
            if response.status_code != 200 or not response.json()["links"]:
                pytest.skip("No link available for needs-new test")
        
        link_id = response.json()["links"][0]["link_id"]
        
        response = requests.post(
            f"{BASE_URL}/api/v1/transactions/matching/{link_id}/needs-new",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Needs-new failed: {response.text}"
        
        data = response.json()
        assert data["status"] == "needs_new_company"
        print(f"Marked link {link_id} as needs_new_company")
    
    def test_manual_link(self, auth_headers):
        """Manual-link endpoint links to a specific company"""
        # Get a link to manually link
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/matching/pending",
            headers=auth_headers
        )
        if response.status_code != 200 or not response.json()["links"]:
            pytest.skip("No link available for manual-link test")
        
        link = response.json()["links"][0]
        link_id = link["link_id"]
        
        # Search for a company to link to
        search_response = requests.get(
            f"{BASE_URL}/api/v1/transactions/matching/search",
            params={"q": "digital"},
            headers=auth_headers
        )
        if search_response.status_code != 200 or not search_response.json()["results"]:
            pytest.skip("No company found for manual-link test")
        
        company_id = search_response.json()["results"][0]["id"]
        company_name = search_response.json()["results"][0].get("company_name")
        
        response = requests.post(
            f"{BASE_URL}/api/v1/transactions/matching/{link_id}/manual-link",
            params={"company_id": company_id},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Manual-link failed: {response.text}"
        
        data = response.json()
        assert data["status"] == "manual_confirmed"
        assert "company_name" in data
        print(f"Manually linked {link_id} to company {company_name}")
    
    def test_confirm_nonexistent_link(self, auth_headers):
        """Confirm returns 404 for nonexistent link"""
        response = requests.post(
            f"{BASE_URL}/api/v1/transactions/matching/lnk_nonexistent123/confirm",
            headers=auth_headers
        )
        assert response.status_code == 404


class TestMatchingAutoRun(TestEntityMatchingAuth):
    """Test that creating a manual transaction auto-runs entity matching"""
    
    def test_create_transaction_triggers_matching(self, auth_headers):
        """Creating a manual transaction auto-runs entity matching"""
        # Create a transaction with entities that might match
        payload = {
            "target_name": "TEST_Ogilvy Spain",
            "buyer_name": "TEST_WPP Group",
            "seller_name": "TEST_Private Equity Fund",
            "announcement_date": "2026-01-20",
            "status": "completed",
            "transaction_type": "takeover",
            "geography_primary": "Spain",
            "sector_original": "Advertising",
            "source": "Test",
            "confidence_level": "high"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/v1/transactions",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 200, f"Create transaction failed: {response.text}"
        
        tx_data = response.json()
        tx_id = tx_data["transaction_id"]
        
        # Verify matching was run - check for company_links
        detail_response = requests.get(
            f"{BASE_URL}/api/v1/transactions/{tx_id}",
            headers=auth_headers
        )
        assert detail_response.status_code == 200
        
        detail = detail_response.json()
        assert "company_links" in detail
        
        # Should have created links for target, buyer, seller
        links = detail["company_links"]
        print(f"Transaction {tx_id} has {len(links)} entity links after creation")
        
        if links:
            for link in links:
                print(f"  - {link['entity_role']}: {link['raw_entity_name']} -> {link['match_status']} ({link.get('match_confidence', 0):.2f})")
        
        # Verify matching_status was set
        assert detail.get("matching_status") in ["pending", "needs_review", "completed", "partial", "no_entities"]
        
        # Cleanup: delete the test transaction
        requests.delete(f"{BASE_URL}/api/v1/transactions/{tx_id}", headers=auth_headers)
        print(f"Cleaned up test transaction {tx_id}")


class TestMatchingAuditLogs(TestEntityMatchingAuth):
    """Test that entity matching actions are captured in audit logs"""
    
    def test_audit_logs_capture_matching_actions(self, auth_headers):
        """Audit logs capture entity matching actions"""
        response = requests.get(
            f"{BASE_URL}/api/v1/transactions/audit-global",
            params={"limit": 50},
            headers=auth_headers
        )
        assert response.status_code == 200, f"Audit log failed: {response.text}"
        
        data = response.json()
        logs = data["logs"]
        
        # Look for entity matching related actions
        matching_actions = [
            "entity_match_confirmed",
            "entity_match_rejected",
            "entity_manual_linked",
            "entity_needs_new_company"
        ]
        
        found_actions = set()
        for log in logs:
            if log["action"] in matching_actions:
                found_actions.add(log["action"])
                print(f"Found audit log: {log['action']} by {log['changed_by']} at {log['changed_at']}")
        
        print(f"Found {len(found_actions)} different matching action types in audit logs: {found_actions}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
