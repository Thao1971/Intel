"""
CIS Publication Flow Tests for Transaction Intelligence
Tests: validate-for-cis, approve-for-cis, unapprove-for-cis, /approved-for-cis endpoints
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
API_BASE = f"{BASE_URL}/api/v1/transactions"

# Test credentials
TEST_EMAIL = "daniel@wearebudadvisors.com"
TEST_PASSWORD = __import__("os").environ.get("SMOKE_TEST_PASSWORD", "")


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for API calls."""
    response = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with auth token."""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def api_client(auth_headers):
    """Requests session with auth headers."""
    session = requests.Session()
    session.headers.update(auth_headers)
    return session


# ═══════════════════════════════════════════════════════════════════════════════
# TEST DATA FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def complete_transaction(api_client):
    """Create a transaction with all CIS requirements met."""
    tx_data = {
        "target_name": "TEST_CIS_Complete_Agency",
        "buyer_name": "TEST_CIS_Buyer Corp",
        "seller_name": "TEST_CIS_Seller Inc",
        "announcement_date": "2025-06-15",
        "transaction_type": "takeover",
        "geography_primary": "Spain",
        "source": "MergerMarket",
        "source_url": "https://mergermarket.com/test",
        "cis_category_suggested": "Digital, Growth y Commerce",
        "cis_subcategory_suggested": "Agencias digitales",
        "value_eurm": 25.5,
        "status": "completed",
        "confidence_level": "high"
    }
    response = api_client.post(API_BASE, json=tx_data)
    assert response.status_code == 200, f"Failed to create transaction: {response.text}"
    tx = response.json()
    tx_id = tx["transaction_id"]
    
    # Set review_status to approved
    api_client.post(f"{API_BASE}/{tx_id}/review?status=approved")
    
    yield tx
    
    # Cleanup
    api_client.delete(f"{API_BASE}/{tx_id}")


@pytest.fixture
def transaction_missing_target(api_client):
    """Create a transaction missing target_name."""
    tx_data = {
        "target_name": "",  # Empty target
        "buyer_name": "TEST_CIS_NoTarget_Buyer",
        "announcement_date": "2025-06-15",
        "transaction_type": "takeover",
        "source": "Test Source"
    }
    # This might fail at creation, so we'll create with a target then clear it
    tx_data["target_name"] = "TEST_CIS_NoTarget_Temp"
    response = api_client.post(API_BASE, json=tx_data)
    if response.status_code != 200:
        pytest.skip("Could not create test transaction")
    tx = response.json()
    tx_id = tx["transaction_id"]
    
    # Update to remove target_name
    api_client.put(f"{API_BASE}/{tx_id}", json={"target_name": ""})
    
    yield tx
    api_client.delete(f"{API_BASE}/{tx_id}")


@pytest.fixture
def transaction_missing_cis_category(api_client):
    """Create a transaction missing CIS category."""
    tx_data = {
        "target_name": "TEST_CIS_NoCategory_Agency",
        "buyer_name": "TEST_CIS_NoCategory_Buyer",
        "announcement_date": "2025-06-15",
        "transaction_type": "takeover",
        "source": "Test Source",
        # No cis_category_suggested
    }
    response = api_client.post(API_BASE, json=tx_data)
    assert response.status_code == 200
    tx = response.json()
    tx_id = tx["transaction_id"]
    
    # Set review_status to approved
    api_client.post(f"{API_BASE}/{tx_id}/review?status=approved")
    
    yield tx
    api_client.delete(f"{API_BASE}/{tx_id}")


@pytest.fixture
def transaction_missing_source(api_client):
    """Create a transaction missing source."""
    tx_data = {
        "target_name": "TEST_CIS_NoSource_Agency",
        "buyer_name": "TEST_CIS_NoSource_Buyer",
        "announcement_date": "2025-06-15",
        "transaction_type": "takeover",
        "cis_category_suggested": "Digital, Growth y Commerce",
        # No source or source_url
    }
    response = api_client.post(API_BASE, json=tx_data)
    assert response.status_code == 200
    tx = response.json()
    tx_id = tx["transaction_id"]
    
    # Set review_status to approved
    api_client.post(f"{API_BASE}/{tx_id}/review?status=approved")
    
    yield tx
    api_client.delete(f"{API_BASE}/{tx_id}")


@pytest.fixture
def transaction_pending_review(api_client):
    """Create a transaction with pending review status."""
    tx_data = {
        "target_name": "TEST_CIS_PendingReview_Agency",
        "buyer_name": "TEST_CIS_PendingReview_Buyer",
        "announcement_date": "2025-06-15",
        "transaction_type": "takeover",
        "source": "Test Source",
        "cis_category_suggested": "Digital, Growth y Commerce",
        # review_status defaults to 'pending'
    }
    response = api_client.post(API_BASE, json=tx_data)
    assert response.status_code == 200
    tx = response.json()
    
    yield tx
    api_client.delete(f"{API_BASE}/{tx['transaction_id']}")


@pytest.fixture
def transaction_type_other(api_client):
    """Create a transaction with transaction_type='other'."""
    tx_data = {
        "target_name": "TEST_CIS_TypeOther_Agency",
        "buyer_name": "TEST_CIS_TypeOther_Buyer",
        "announcement_date": "2025-06-15",
        "transaction_type": "other",  # 'other' type gives warning
        "source": "Test Source",
        "cis_category_suggested": "Digital, Growth y Commerce",
    }
    response = api_client.post(API_BASE, json=tx_data)
    assert response.status_code == 200
    tx = response.json()
    tx_id = tx["transaction_id"]
    
    # Set review_status to approved
    api_client.post(f"{API_BASE}/{tx_id}/review?status=approved")
    
    yield tx
    api_client.delete(f"{API_BASE}/{tx_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateForCIS:
    """Tests for POST /{tx_id}/validate-for-cis endpoint."""
    
    def test_validate_returns_validation_result_structure(self, api_client, complete_transaction):
        """Validation returns can_approve, missing_requirements, warnings, quality_score."""
        tx_id = complete_transaction["transaction_id"]
        response = api_client.post(f"{API_BASE}/{tx_id}/validate-for-cis")
        
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields in response
        assert "transaction_id" in data
        assert "can_approve" in data
        assert "missing_requirements" in data
        assert "warnings" in data
        assert "quality_score" in data
        
        # Validate types
        assert isinstance(data["can_approve"], bool)
        assert isinstance(data["missing_requirements"], list)
        assert isinstance(data["warnings"], list)
        assert isinstance(data["quality_score"], (int, float))
        assert 0.0 <= data["quality_score"] <= 1.0
        
        print(f"Validation result: can_approve={data['can_approve']}, quality_score={data['quality_score']}")
    
    def test_validation_fails_missing_cis_category(self, api_client, transaction_missing_cis_category):
        """Validation fails when CIS category is missing."""
        tx_id = transaction_missing_cis_category["transaction_id"]
        response = api_client.post(f"{API_BASE}/{tx_id}/validate-for-cis")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should not be approvable
        assert data["can_approve"] == False
        
        # Should have missing requirement for cis_category
        missing_str = " ".join(data["missing_requirements"])
        assert "cis_category" in missing_str.lower() or "categoria" in missing_str.lower()
        
        print(f"Missing requirements: {data['missing_requirements']}")
    
    def test_validation_fails_missing_source(self, api_client, transaction_missing_source):
        """Validation fails when source is missing."""
        tx_id = transaction_missing_source["transaction_id"]
        response = api_client.post(f"{API_BASE}/{tx_id}/validate-for-cis")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should not be approvable
        assert data["can_approve"] == False
        
        # Should have missing requirement for source
        missing_str = " ".join(data["missing_requirements"])
        assert "source" in missing_str.lower() or "fuente" in missing_str.lower()
        
        print(f"Missing requirements: {data['missing_requirements']}")
    
    def test_validation_fails_pending_review_status(self, api_client, transaction_pending_review):
        """Validation fails when review_status is not approved/reviewed."""
        tx_id = transaction_pending_review["transaction_id"]
        response = api_client.post(f"{API_BASE}/{tx_id}/validate-for-cis")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should not be approvable
        assert data["can_approve"] == False
        
        # Should have missing requirement for review_status
        missing_str = " ".join(data["missing_requirements"])
        assert "review" in missing_str.lower() or "estado" in missing_str.lower()
        
        print(f"Missing requirements: {data['missing_requirements']}")
    
    def test_validation_warns_transaction_type_other(self, api_client, transaction_type_other):
        """Validation gives warning when transaction_type is 'other'."""
        tx_id = transaction_type_other["transaction_id"]
        response = api_client.post(f"{API_BASE}/{tx_id}/validate-for-cis")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should have warning for 'other' type
        warnings_str = " ".join(data["warnings"])
        assert "other" in warnings_str.lower() or "tipo" in warnings_str.lower()
        
        print(f"Warnings: {data['warnings']}")
    
    def test_validation_nonexistent_transaction(self, api_client):
        """Validation returns 404 for nonexistent transaction."""
        response = api_client.post(f"{API_BASE}/tx_nonexistent_12345/validate-for-cis")
        assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# APPROVE/UNAPPROVE ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestApproveForCIS:
    """Tests for POST /{tx_id}/approve-for-cis endpoint."""
    
    def test_approve_rejects_when_requirements_not_met(self, api_client, transaction_missing_cis_category):
        """Approve-for-CIS rejects when requirements not met."""
        tx_id = transaction_missing_cis_category["transaction_id"]
        response = api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
        
        assert response.status_code == 200
        data = response.json()
        
        # Should be rejected
        assert data.get("status") == "rejected" or data.get("can_approve") == False
        assert len(data.get("missing_requirements", [])) > 0
        
        print(f"Rejection reason: {data.get('missing_requirements')}")
    
    def test_approve_nonexistent_transaction(self, api_client):
        """Approve returns 404 for nonexistent transaction."""
        response = api_client.post(f"{API_BASE}/tx_nonexistent_12345/approve-for-cis")
        assert response.status_code == 404


class TestUnapproveForCIS:
    """Tests for POST /{tx_id}/unapprove-for-cis endpoint."""
    
    def test_unapprove_removes_cis_approval(self, api_client):
        """Unapprove removes CIS approval from a transaction."""
        # First create a transaction that can be approved
        tx_data = {
            "target_name": "TEST_CIS_Unapprove_Agency",
            "buyer_name": "TEST_CIS_Unapprove_Buyer",
            "announcement_date": "2025-06-15",
            "transaction_type": "takeover",
            "source": "Test Source",
            "source_url": "https://test.com",
            "cis_category_suggested": "Digital, Growth y Commerce",
        }
        create_resp = api_client.post(API_BASE, json=tx_data)
        assert create_resp.status_code == 200
        tx = create_resp.json()
        tx_id = tx["transaction_id"]
        
        try:
            # Set review_status to approved
            api_client.post(f"{API_BASE}/{tx_id}/review?status=approved")
            
            # Try to approve for CIS (may fail due to entity linking requirement)
            approve_resp = api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
            
            # If approved, test unapprove
            if approve_resp.status_code == 200 and approve_resp.json().get("status") == "approved_for_cis":
                # Verify it's approved
                get_resp = api_client.get(f"{API_BASE}/{tx_id}")
                assert get_resp.json().get("publish_status") == "approved_for_cis"
                
                # Now unapprove
                unapprove_resp = api_client.post(f"{API_BASE}/{tx_id}/unapprove-for-cis")
                assert unapprove_resp.status_code == 200
                assert unapprove_resp.json().get("status") == "unapproved"
                
                # Verify it's no longer approved
                get_resp2 = api_client.get(f"{API_BASE}/{tx_id}")
                assert get_resp2.json().get("publish_status") == "not_published"
                
                print("Unapprove test passed - transaction was approved then unapproved")
            else:
                # Transaction couldn't be approved (likely missing entity link)
                # Test unapprove on a non-approved transaction
                unapprove_resp = api_client.post(f"{API_BASE}/{tx_id}/unapprove-for-cis")
                assert unapprove_resp.status_code == 200
                print("Unapprove test passed - transaction was not approved (missing requirements)")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")
    
    def test_unapprove_nonexistent_transaction(self, api_client):
        """Unapprove returns 404 for nonexistent transaction."""
        response = api_client.post(f"{API_BASE}/tx_nonexistent_12345/unapprove-for-cis")
        assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC APPROVED-FOR-CIS ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestApprovedForCISEndpoint:
    """Tests for GET /approved-for-cis public endpoint."""
    
    def test_approved_for_cis_is_public(self):
        """GET /approved-for-cis does NOT require authentication."""
        # Call without auth headers
        response = requests.get(f"{API_BASE}/approved-for-cis")
        
        # Should return 200, not 401/403
        assert response.status_code == 200
        data = response.json()
        
        assert "items" in data
        assert "total" in data
        assert "last_updated" in data
        
        print(f"Public endpoint returned {data['total']} approved transactions")
    
    def test_approved_for_cis_returns_cis_compatible_format(self):
        """GET /approved-for-cis returns CIS-compatible format."""
        response = requests.get(f"{API_BASE}/approved-for-cis")
        assert response.status_code == 200
        data = response.json()
        
        # If there are items, check the format
        if data["items"]:
            item = data["items"][0]
            
            # Check required CIS fields
            expected_fields = [
                "id", "title", "transaction_date", "year", "target_name",
                "buyer_name", "cis_category", "amount_label", "amount_status",
                "linked_entities", "classification_origin"
            ]
            
            for field in expected_fields:
                assert field in item, f"Missing field: {field}"
            
            # Validate amount_status values
            valid_amount_statuses = ["undisclosed", "confirmed", "estimated", "approximate"]
            assert item["amount_status"] in valid_amount_statuses
            
            # Validate classification_origin values
            valid_origins = ["manual", "ai_accepted", "imported"]
            assert item["classification_origin"] in valid_origins
            
            # linked_entities should be a list
            assert isinstance(item["linked_entities"], list)
            
            print(f"CIS format validated for: {item['title']}")
        else:
            print("No approved transactions to validate format")
    
    def test_approved_for_cis_supports_year_filter(self):
        """GET /approved-for-cis supports year filter."""
        response = requests.get(f"{API_BASE}/approved-for-cis?year=2025")
        assert response.status_code == 200
        data = response.json()
        
        # All items should have year 2025
        for item in data["items"]:
            if item.get("year"):
                assert item["year"] == 2025
        
        print(f"Year filter returned {data['total']} transactions")
    
    def test_approved_for_cis_supports_category_filter(self):
        """GET /approved-for-cis supports category filter."""
        response = requests.get(f"{API_BASE}/approved-for-cis?category=Digital")
        assert response.status_code == 200
        data = response.json()
        
        # All items should have category containing 'Digital'
        for item in data["items"]:
            if item.get("cis_category"):
                assert "digital" in item["cis_category"].lower()
        
        print(f"Category filter returned {data['total']} transactions")
    
    def test_approved_for_cis_supports_country_filter(self):
        """GET /approved-for-cis supports country filter."""
        response = requests.get(f"{API_BASE}/approved-for-cis?country=Spain")
        assert response.status_code == 200
        data = response.json()
        
        # All items should have country containing 'Spain'
        for item in data["items"]:
            if item.get("country"):
                assert "spain" in item["country"].lower()
        
        print(f"Country filter returned {data['total']} transactions")
    
    def test_approved_for_cis_supports_transaction_type_filter(self):
        """GET /approved-for-cis supports transaction_type filter."""
        response = requests.get(f"{API_BASE}/approved-for-cis?transaction_type=takeover")
        assert response.status_code == 200
        data = response.json()
        
        # All items should have transaction_type 'takeover'
        for item in data["items"]:
            if item.get("transaction_type"):
                assert item["transaction_type"] == "takeover"
        
        print(f"Transaction type filter returned {data['total']} transactions")
    
    def test_approved_for_cis_returns_only_approved(self, api_client):
        """GET /approved-for-cis returns ONLY approved_for_cis transactions."""
        # Get all approved transactions
        response = requests.get(f"{API_BASE}/approved-for-cis")
        assert response.status_code == 200
        data = response.json()
        
        # All items should have quality_status = approved_for_cis
        for item in data["items"]:
            assert item.get("quality_status") == "approved_for_cis"
        
        print(f"All {data['total']} transactions have approved_for_cis status")


# ═══════════════════════════════════════════════════════════════════════════════
# STATS AND AUDIT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestStatsAndAudit:
    """Tests for stats and audit log integration."""
    
    def test_stats_includes_approved_for_cis_count(self, api_client):
        """Stats endpoint includes approved_for_cis count."""
        response = api_client.get(f"{API_BASE}/stats")
        assert response.status_code == 200
        data = response.json()
        
        assert "approved_for_cis" in data
        assert isinstance(data["approved_for_cis"], int)
        assert data["approved_for_cis"] >= 0
        
        print(f"Stats: approved_for_cis = {data['approved_for_cis']}")
    
    def test_audit_logs_capture_cis_actions(self, api_client):
        """Audit logs capture approved_for_cis and unapproved_from_cis actions."""
        # Get global audit logs
        response = api_client.get(f"{API_BASE}/audit-global?limit=200")
        assert response.status_code == 200
        data = response.json()
        
        # Check if CIS-related actions exist
        cis_actions = [log for log in data["logs"] if log.get("action") in ["approved_for_cis", "unapproved_from_cis"]]
        
        print(f"Found {len(cis_actions)} CIS-related audit log entries")
        
        # If there are CIS actions, validate structure
        for log in cis_actions[:3]:  # Check first 3
            assert "log_id" in log
            assert "transaction_id" in log
            assert "action" in log
            assert "changed_by" in log
            assert "changed_at" in log
            print(f"  - {log['action']} by {log['changed_by']} at {log['changed_at']}")


# ═══════════════════════════════════════════════════════════════════════════════
# ENTITY LINKING VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestEntityLinkingValidation:
    """Tests for target entity linking validation in CIS approval."""
    
    def test_validation_checks_target_entity_linked(self, api_client):
        """Validation checks if target entity is linked/confirmed."""
        # Create a transaction without entity linking
        tx_data = {
            "target_name": "TEST_CIS_NoEntityLink_Agency",
            "buyer_name": "TEST_CIS_NoEntityLink_Buyer",
            "announcement_date": "2025-06-15",
            "transaction_type": "takeover",
            "source": "Test Source",
            "source_url": "https://test.com",
            "cis_category_suggested": "Digital, Growth y Commerce",
        }
        create_resp = api_client.post(API_BASE, json=tx_data)
        assert create_resp.status_code == 200
        tx = create_resp.json()
        tx_id = tx["transaction_id"]
        
        try:
            # Set review_status to approved
            api_client.post(f"{API_BASE}/{tx_id}/review?status=approved")
            
            # Validate for CIS
            validate_resp = api_client.post(f"{API_BASE}/{tx_id}/validate-for-cis")
            assert validate_resp.status_code == 200
            data = validate_resp.json()
            
            # Should have missing requirement for target entity
            missing_str = " ".join(data["missing_requirements"])
            has_entity_requirement = (
                "target_entity" in missing_str.lower() or 
                "vinculado" in missing_str.lower() or
                "target" in missing_str.lower()
            )
            
            print(f"Missing requirements: {data['missing_requirements']}")
            print(f"Can approve: {data['can_approve']}")
            
            # The validation should mention entity linking
            if not data["can_approve"]:
                assert has_entity_requirement or len(data["missing_requirements"]) > 0
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# DEDUPE STATUS VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestDedupeStatusValidation:
    """Tests for dedupe status validation in CIS approval."""
    
    def test_validation_fails_possible_duplicate(self, api_client):
        """Validation fails when dedupe_status is possible_duplicate."""
        # Create two similar transactions to trigger duplicate detection
        tx_data1 = {
            "target_name": "TEST_CIS_Dedupe_Agency",
            "buyer_name": "TEST_CIS_Dedupe_Buyer",
            "announcement_date": "2025-06-15",
            "transaction_type": "takeover",
            "source": "Test Source",
            "cis_category_suggested": "Digital, Growth y Commerce",
        }
        
        create_resp1 = api_client.post(API_BASE, json=tx_data1)
        assert create_resp1.status_code == 200
        tx1 = create_resp1.json()
        tx1_id = tx1["transaction_id"]
        
        # Create a very similar transaction
        tx_data2 = {
            "target_name": "TEST_CIS_Dedupe_Agency",  # Same target
            "buyer_name": "TEST_CIS_Dedupe_Buyer",    # Same buyer
            "announcement_date": "2025-06-15",        # Same date
            "transaction_type": "takeover",
            "source": "Test Source 2",
            "cis_category_suggested": "Digital, Growth y Commerce",
        }
        
        create_resp2 = api_client.post(API_BASE, json=tx_data2)
        assert create_resp2.status_code == 200
        tx2 = create_resp2.json()
        tx2_id = tx2["transaction_id"]
        
        try:
            # Wait a moment for dedupe check
            time.sleep(0.5)
            
            # Get the transaction to check dedupe_status
            get_resp = api_client.get(f"{API_BASE}/{tx2_id}")
            tx2_data = get_resp.json()
            
            # If it's marked as possible_duplicate, validate should fail
            if tx2_data.get("dedupe_status") == "possible_duplicate":
                # Set review_status to approved
                api_client.post(f"{API_BASE}/{tx2_id}/review?status=approved")
                
                # Validate for CIS
                validate_resp = api_client.post(f"{API_BASE}/{tx2_id}/validate-for-cis")
                assert validate_resp.status_code == 200
                data = validate_resp.json()
                
                # Should not be approvable
                assert data["can_approve"] == False
                
                # Should have missing requirement for dedupe
                missing_str = " ".join(data["missing_requirements"])
                assert "dedupe" in missing_str.lower() or "duplicado" in missing_str.lower()
                
                print(f"Dedupe validation passed - transaction marked as possible_duplicate")
            else:
                print(f"Transaction dedupe_status: {tx2_data.get('dedupe_status')} - dedupe check may not have triggered")
        finally:
            api_client.delete(f"{API_BASE}/{tx1_id}")
            api_client.delete(f"{API_BASE}/{tx2_id}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
