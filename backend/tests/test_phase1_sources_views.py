"""
Phase 1 Backend Tests for Transaction Intelligence
Tests: Sources CRUD, visible_status computation, CIS sync detection, withdrawal with reason,
       updated approved-for-cis endpoint, view endpoints (needs-review, ready-for-cis, published),
       external_entity match status, update-cis endpoint.

WITHDRAWAL_REASONS = ['incorrect_information', 'duplicate_operation', 'unconfirmed_operation', 
                      'out_of_scope', 'import_error', 'other']
CIS_CRITICAL_FIELDS = target_name, buyer_name, seller_name, announcement_date, transaction_type,
                      cis_category_suggested, cis_subcategory_suggested, value_eurm, amount_status,
                      valuation_basis, ve_sales, ve_ebitda, revenue_eurm, ebitda_eurm, ev_eurm,
                      summary, strategic_rationale, geography_primary
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


def create_cis_ready_transaction(api_client, name_suffix=""):
    """Helper to create a transaction that can be approved for CIS."""
    tx_data = {
        "target_name": f"TEST_CIS_{name_suffix}_Target",
        "buyer_name": f"TEST_CIS_{name_suffix}_Buyer",
        "announcement_date": "2025-06-15",
        "transaction_type": "takeover",
        "geography_primary": "Spain",
        "cis_category_suggested": "Digital, Growth y Commerce",
        "summary": "Test summary for CIS approval",
        "source": "Test Source",
        "source_url": "https://test.com"
    }
    response = api_client.post(API_BASE, json=tx_data)
    assert response.status_code == 200, f"Failed to create transaction: {response.text}"
    tx = response.json()
    tx_id = tx["transaction_id"]
    
    # Get target link and mark as external entity
    get_resp = api_client.get(f"{API_BASE}/{tx_id}")
    links = get_resp.json().get("company_links", [])
    target_link = next((l for l in links if l.get("entity_role") == "target"), None)
    if target_link:
        api_client.post(f"{API_BASE}/matching/{target_link['link_id']}/external-entity")
    
    # Approve review
    api_client.post(f"{API_BASE}/{tx_id}/review?status=approved")
    
    return tx


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCES CRUD TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSourcesCRUD:
    """Tests for transaction sources CRUD operations."""
    
    @pytest.fixture
    def test_transaction(self, api_client):
        """Create a test transaction for source tests."""
        tx_data = {
            "target_name": "TEST_SOURCES_Target",
            "buyer_name": "TEST_SOURCES_Buyer",
            "announcement_date": "2025-06-15",
            "transaction_type": "takeover",
            "geography_primary": "Spain",
            "cis_category_suggested": "Digital, Growth y Commerce",
            "summary": "Test transaction for sources testing"
        }
        response = api_client.post(API_BASE, json=tx_data)
        assert response.status_code == 200, f"Failed to create transaction: {response.text}"
        tx = response.json()
        yield tx
        # Cleanup
        api_client.delete(f"{API_BASE}/{tx['transaction_id']}")
    
    def test_create_source_with_all_fields(self, api_client, test_transaction):
        """POST /sources/{tx_id} creates a source with is_primary, publisher, url, source_type."""
        tx_id = test_transaction["transaction_id"]
        source_data = {
            "title": "Test Article Title",
            "publisher": "MergerMarket",
            "url": "https://mergermarket.com/test-article",
            "published_at": "2025-06-10",
            "source_type": "press_article",
            "is_primary": True,
            "summary": "Article summary",
            "notes": "Internal notes"
        }
        response = api_client.post(f"{API_BASE}/sources/{tx_id}", json=source_data)
        assert response.status_code == 200, f"Failed to create source: {response.text}"
        
        source = response.json()
        assert source["source_id"].startswith("src_"), "Source ID should start with 'src_'"
        assert source["transaction_id"] == tx_id
        assert source["publisher"] == "MergerMarket"
        assert source["url"] == "https://mergermarket.com/test-article"
        assert source["source_type"] == "press_article"
        assert source["is_primary"] == True
        assert source["title"] == "Test Article Title"
        print(f"✓ Created source {source['source_id']} with all fields")
    
    def test_create_source_sets_primary_unsets_others(self, api_client, test_transaction):
        """Setting is_primary=true unsets other primaries."""
        tx_id = test_transaction["transaction_id"]
        
        # Create first source as primary
        source1_data = {
            "publisher": "Source1",
            "url": "https://source1.com",
            "source_type": "press_article",
            "is_primary": True
        }
        resp1 = api_client.post(f"{API_BASE}/sources/{tx_id}", json=source1_data)
        assert resp1.status_code == 200
        source1_id = resp1.json()["source_id"]
        
        # Create second source as primary
        source2_data = {
            "publisher": "Source2",
            "url": "https://source2.com",
            "source_type": "press_release",
            "is_primary": True
        }
        resp2 = api_client.post(f"{API_BASE}/sources/{tx_id}", json=source2_data)
        assert resp2.status_code == 200
        source2_id = resp2.json()["source_id"]
        
        # List sources and verify only source2 is primary
        list_resp = api_client.get(f"{API_BASE}/sources/{tx_id}")
        assert list_resp.status_code == 200
        sources = list_resp.json()["sources"]
        
        source1 = next((s for s in sources if s["source_id"] == source1_id), None)
        source2 = next((s for s in sources if s["source_id"] == source2_id), None)
        
        assert source1 is not None and source1["is_primary"] == False, "First source should no longer be primary"
        assert source2 is not None and source2["is_primary"] == True, "Second source should be primary"
        print("✓ Setting is_primary=true correctly unsets other primaries")
    
    def test_update_source_fields(self, api_client, test_transaction):
        """PUT /sources/{tx_id}/{source_id} updates source fields."""
        tx_id = test_transaction["transaction_id"]
        
        # Create a source
        create_resp = api_client.post(f"{API_BASE}/sources/{tx_id}", json={
            "publisher": "Original Publisher",
            "url": "https://original.com",
            "source_type": "press_article"
        })
        assert create_resp.status_code == 200
        source_id = create_resp.json()["source_id"]
        
        # Update the source
        update_data = {
            "publisher": "Updated Publisher",
            "url": "https://updated.com",
            "source_type": "press_release",
            "is_primary": True
        }
        update_resp = api_client.put(f"{API_BASE}/sources/{tx_id}/{source_id}", json=update_data)
        assert update_resp.status_code == 200
        
        updated = update_resp.json()
        assert updated["publisher"] == "Updated Publisher"
        assert updated["url"] == "https://updated.com"
        assert updated["source_type"] == "press_release"
        assert updated["is_primary"] == True
        print(f"✓ Updated source {source_id} fields successfully")
    
    def test_delete_source(self, api_client, test_transaction):
        """DELETE /sources/{tx_id}/{source_id} deletes a source."""
        tx_id = test_transaction["transaction_id"]
        
        # Create a source
        create_resp = api_client.post(f"{API_BASE}/sources/{tx_id}", json={
            "publisher": "To Delete",
            "url": "https://delete.com",
            "source_type": "other"
        })
        assert create_resp.status_code == 200
        source_id = create_resp.json()["source_id"]
        
        # Delete the source
        delete_resp = api_client.delete(f"{API_BASE}/sources/{tx_id}/{source_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["status"] == "deleted"
        
        # Verify it's gone
        list_resp = api_client.get(f"{API_BASE}/sources/{tx_id}")
        sources = list_resp.json()["sources"]
        assert not any(s["source_id"] == source_id for s in sources), "Deleted source should not appear in list"
        print(f"✓ Deleted source {source_id} successfully")
    
    def test_list_sources_for_transaction(self, api_client, test_transaction):
        """GET /sources/{tx_id} lists sources for a transaction."""
        tx_id = test_transaction["transaction_id"]
        
        # Create multiple sources
        for i in range(3):
            api_client.post(f"{API_BASE}/sources/{tx_id}", json={
                "publisher": f"Publisher {i}",
                "url": f"https://source{i}.com",
                "source_type": "press_article",
                "is_primary": i == 0
            })
        
        # List sources
        list_resp = api_client.get(f"{API_BASE}/sources/{tx_id}")
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert "sources" in data
        assert len(data["sources"]) >= 3
        print(f"✓ Listed {len(data['sources'])} sources for transaction")


# ═══════════════════════════════════════════════════════════════════════════════
# VISIBLE STATUS & INCIDENCES TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestVisibleStatusAndIncidences:
    """Tests for visible_status computation and incidences in GET /{tx_id}."""
    
    @pytest.fixture
    def published_transaction(self, api_client):
        """Create and approve a transaction for CIS."""
        tx = create_cis_ready_transaction(api_client, "VISIBLE_PUB")
        tx_id = tx["transaction_id"]
        
        # Approve for CIS
        api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
        
        yield tx
        # Cleanup
        api_client.delete(f"{API_BASE}/{tx_id}")
    
    def test_get_transaction_returns_visible_status(self, api_client, published_transaction):
        """GET /{tx_id} returns visible_status field."""
        tx_id = published_transaction["transaction_id"]
        response = api_client.get(f"{API_BASE}/{tx_id}")
        assert response.status_code == 200
        tx = response.json()
        
        assert "visible_status" in tx, "Response should include visible_status"
        assert tx["visible_status"] in [
            "draft", "incomplete", "needs_review", "ready_for_cis",
            "published_in_cis", "pending_sync", "withdrawn_from_cis", "archived"
        ]
        print(f"✓ GET /{tx_id} returns visible_status: {tx['visible_status']}")
    
    def test_get_transaction_returns_incidences(self, api_client, published_transaction):
        """GET /{tx_id} returns incidences array."""
        tx_id = published_transaction["transaction_id"]
        response = api_client.get(f"{API_BASE}/{tx_id}")
        assert response.status_code == 200
        tx = response.json()
        
        assert "incidences" in tx, "Response should include incidences"
        assert isinstance(tx["incidences"], list)
        print(f"✓ GET /{tx_id} returns incidences: {tx['incidences']}")
    
    def test_get_transaction_returns_sources_array(self, api_client, published_transaction):
        """GET /{tx_id} returns sources array."""
        tx_id = published_transaction["transaction_id"]
        response = api_client.get(f"{API_BASE}/{tx_id}")
        assert response.status_code == 200
        tx = response.json()
        
        assert "sources" in tx, "Response should include sources array"
        assert isinstance(tx["sources"], list)
        print(f"✓ GET /{tx_id} returns sources array with {len(tx['sources'])} items")
    
    def test_visible_status_published_in_cis(self, api_client, published_transaction):
        """visible_status returns published_in_cis for approved_for_cis transactions."""
        tx_id = published_transaction["transaction_id"]
        response = api_client.get(f"{API_BASE}/{tx_id}")
        assert response.status_code == 200
        tx = response.json()
        
        assert tx["publish_status"] == "approved_for_cis"
        assert tx["visible_status"] == "published_in_cis", f"Expected published_in_cis, got {tx['visible_status']}"
        print("✓ visible_status returns published_in_cis for approved_for_cis transactions")
    
    def test_visible_status_pending_sync(self, api_client, published_transaction):
        """visible_status returns pending_sync when cis_sync_status=pending_update."""
        tx_id = published_transaction["transaction_id"]
        
        # Edit a critical field to trigger pending_update
        update_resp = api_client.put(f"{API_BASE}/{tx_id}", json={
            "summary": "Updated summary to trigger pending_update"
        })
        assert update_resp.status_code == 200
        
        # Check visible_status
        response = api_client.get(f"{API_BASE}/{tx_id}")
        tx = response.json()
        
        assert tx.get("cis_sync_status") == "pending_update", f"Expected pending_update, got {tx.get('cis_sync_status')}"
        assert tx["visible_status"] == "pending_sync", f"Expected pending_sync, got {tx['visible_status']}"
        print("✓ visible_status returns pending_sync when cis_sync_status=pending_update")
    
    def test_visible_status_withdrawn_from_cis(self, api_client):
        """visible_status returns withdrawn_from_cis for removed_from_cis."""
        tx = create_cis_ready_transaction(api_client, "VISIBLE_WITHDRAW")
        tx_id = tx["transaction_id"]
        
        try:
            # Approve for CIS
            api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
            
            # Withdraw
            withdraw_resp = api_client.post(f"{API_BASE}/{tx_id}/withdraw-from-cis", json={
                "reason": "incorrect_information",
                "notes": "Test withdrawal"
            })
            assert withdraw_resp.status_code == 200, f"Withdraw failed: {withdraw_resp.text}"
            
            # Check visible_status
            response = api_client.get(f"{API_BASE}/{tx_id}")
            tx_data = response.json()
            
            assert tx_data["publish_status"] == "removed_from_cis"
            assert tx_data["visible_status"] == "withdrawn_from_cis", f"Expected withdrawn_from_cis, got {tx_data['visible_status']}"
            print("✓ visible_status returns withdrawn_from_cis for removed_from_cis")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")
    
    def test_visible_status_needs_review_incomplete(self, api_client):
        """visible_status returns needs_review for incomplete transactions."""
        # Create a minimal transaction
        tx_data = {
            "target_name": "TEST_VISIBLE_Incomplete",
            "announcement_date": "2025-06-15",
            "transaction_type": "takeover"
        }
        create_resp = api_client.post(API_BASE, json=tx_data)
        assert create_resp.status_code == 200
        tx_id = create_resp.json()["transaction_id"]
        
        try:
            response = api_client.get(f"{API_BASE}/{tx_id}")
            tx = response.json()
            
            # Should be needs_review or incomplete due to missing requirements
            assert tx["visible_status"] in ["needs_review", "incomplete", "draft"], \
                f"Expected needs_review/incomplete/draft, got {tx['visible_status']}"
            print(f"✓ visible_status returns {tx['visible_status']} for incomplete transactions")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# CIS SYNC DETECTION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestCISSyncDetection:
    """Tests for CIS sync detection (pending_update on critical field edits)."""
    
    def test_edit_critical_field_sets_pending_update(self, api_client):
        """Editing a published tx critical field sets cis_sync_status=pending_update."""
        tx = create_cis_ready_transaction(api_client, "SYNC_CRITICAL")
        tx_id = tx["transaction_id"]
        
        try:
            api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
            
            # Edit a critical field (summary is in CIS_CRITICAL_FIELDS)
            update_resp = api_client.put(f"{API_BASE}/{tx_id}", json={
                "summary": "Modified summary triggers pending_update"
            })
            assert update_resp.status_code == 200
            
            # Verify cis_sync_status
            get_resp = api_client.get(f"{API_BASE}/{tx_id}")
            tx_data = get_resp.json()
            
            assert tx_data.get("cis_sync_status") == "pending_update", \
                f"Expected pending_update after critical field edit, got {tx_data.get('cis_sync_status')}"
            print("✓ Editing critical field (summary) sets cis_sync_status=pending_update")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")
    
    def test_edit_target_name_sets_pending_update(self, api_client):
        """Editing target_name on published tx sets pending_update."""
        tx = create_cis_ready_transaction(api_client, "SYNC_TARGET")
        tx_id = tx["transaction_id"]
        
        try:
            api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
            
            # Edit target_name
            api_client.put(f"{API_BASE}/{tx_id}", json={
                "target_name": "TEST_SYNC_Target_Modified"
            })
            
            get_resp = api_client.get(f"{API_BASE}/{tx_id}")
            tx_data = get_resp.json()
            
            assert tx_data.get("cis_sync_status") == "pending_update"
            print("✓ Editing target_name sets cis_sync_status=pending_update")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")
    
    def test_add_source_on_published_marks_pending_update(self, api_client):
        """Adding source on published tx marks pending_update."""
        tx = create_cis_ready_transaction(api_client, "SYNC_SRCADD")
        tx_id = tx["transaction_id"]
        
        try:
            api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
            
            # Add a source
            api_client.post(f"{API_BASE}/sources/{tx_id}", json={
                "publisher": "New Source",
                "url": "https://newsource.com",
                "source_type": "press_article"
            })
            
            get_resp = api_client.get(f"{API_BASE}/{tx_id}")
            tx_data = get_resp.json()
            
            assert tx_data.get("cis_sync_status") == "pending_update", \
                f"Expected pending_update after adding source, got {tx_data.get('cis_sync_status')}"
            print("✓ Adding source on published tx marks pending_update")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")
    
    def test_delete_source_on_published_marks_pending_update(self, api_client):
        """Deleting source on published tx marks pending_update."""
        tx = create_cis_ready_transaction(api_client, "SYNC_SRCDEL")
        tx_id = tx["transaction_id"]
        
        try:
            # Add a source before approving
            src_resp = api_client.post(f"{API_BASE}/sources/{tx_id}", json={
                "publisher": "Source to Delete",
                "url": "https://todelete.com",
                "source_type": "press_article"
            })
            source_id = src_resp.json()["source_id"]
            
            api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
            
            # Delete the source
            api_client.delete(f"{API_BASE}/sources/{tx_id}/{source_id}")
            
            get_resp = api_client.get(f"{API_BASE}/{tx_id}")
            tx_data = get_resp.json()
            
            assert tx_data.get("cis_sync_status") == "pending_update", \
                f"Expected pending_update after deleting source, got {tx_data.get('cis_sync_status')}"
            print("✓ Deleting source on published tx marks pending_update")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# UPDATE-CIS ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestUpdateCIS:
    """Tests for POST /{tx_id}/update-cis endpoint."""
    
    def test_update_cis_resets_sync_status(self, api_client):
        """POST /{tx_id}/update-cis resets sync to approved_for_cis."""
        tx = create_cis_ready_transaction(api_client, "UPDATE_CIS")
        tx_id = tx["transaction_id"]
        
        try:
            api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
            
            # Edit to trigger pending_update
            api_client.put(f"{API_BASE}/{tx_id}", json={"summary": "Modified summary"})
            
            # Verify pending_update
            get_resp = api_client.get(f"{API_BASE}/{tx_id}")
            assert get_resp.json().get("cis_sync_status") == "pending_update"
            
            # Call update-cis
            update_cis_resp = api_client.post(f"{API_BASE}/{tx_id}/update-cis")
            assert update_cis_resp.status_code == 200
            result = update_cis_resp.json()
            assert result["status"] == "updated"
            
            # Verify sync status reset
            get_resp2 = api_client.get(f"{API_BASE}/{tx_id}")
            tx_data = get_resp2.json()
            assert tx_data.get("cis_sync_status") == "approved_for_cis", \
                f"Expected approved_for_cis after update-cis, got {tx_data.get('cis_sync_status')}"
            print("✓ POST /{tx_id}/update-cis resets sync to approved_for_cis")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")
    
    def test_update_cis_fails_for_unpublished(self, api_client):
        """POST /{tx_id}/update-cis fails for unpublished transaction."""
        tx_data = {
            "target_name": "TEST_UPDATE_CIS_Unpub",
            "announcement_date": "2025-06-15",
            "transaction_type": "takeover"
        }
        create_resp = api_client.post(API_BASE, json=tx_data)
        tx_id = create_resp.json()["transaction_id"]
        
        try:
            update_cis_resp = api_client.post(f"{API_BASE}/{tx_id}/update-cis")
            assert update_cis_resp.status_code == 400
            print("✓ POST /{tx_id}/update-cis returns 400 for unpublished transaction")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# WITHDRAWAL TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestWithdrawal:
    """Tests for POST /{tx_id}/withdraw-from-cis endpoint."""
    
    VALID_REASONS = [
        "incorrect_information", "duplicate_operation", "unconfirmed_operation",
        "out_of_scope", "import_error", "other"
    ]
    
    def test_withdraw_requires_reason(self, api_client):
        """POST /{tx_id}/withdraw-from-cis requires reason from WITHDRAWAL_REASONS list."""
        tx = create_cis_ready_transaction(api_client, "WITHDRAW_REASON")
        tx_id = tx["transaction_id"]
        
        try:
            api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
            
            # Try with invalid reason
            invalid_resp = api_client.post(f"{API_BASE}/{tx_id}/withdraw-from-cis", json={
                "reason": "invalid_reason"
            })
            assert invalid_resp.status_code == 400, "Should reject invalid reason"
            
            # Try with valid reason
            valid_resp = api_client.post(f"{API_BASE}/{tx_id}/withdraw-from-cis", json={
                "reason": "incorrect_information",
                "notes": "Test notes"
            })
            assert valid_resp.status_code == 200
            print("✓ POST /{tx_id}/withdraw-from-cis requires valid reason from WITHDRAWAL_REASONS")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")
    
    def test_withdraw_sets_removed_from_cis(self, api_client):
        """POST /{tx_id}/withdraw-from-cis sets publish_status=removed_from_cis."""
        tx = create_cis_ready_transaction(api_client, "WITHDRAW_STATUS")
        tx_id = tx["transaction_id"]
        
        try:
            api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
            
            withdraw_resp = api_client.post(f"{API_BASE}/{tx_id}/withdraw-from-cis", json={
                "reason": "duplicate_operation"
            })
            assert withdraw_resp.status_code == 200
            assert withdraw_resp.json()["status"] == "withdrawn"
            
            get_resp = api_client.get(f"{API_BASE}/{tx_id}")
            tx_data = get_resp.json()
            assert tx_data["publish_status"] == "removed_from_cis"
            assert tx_data["withdrawal_reason"] == "duplicate_operation"
            print("✓ POST /{tx_id}/withdraw-from-cis sets publish_status=removed_from_cis")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")
    
    def test_withdrawn_disappears_from_approved_for_cis(self, api_client):
        """Withdrawn transactions disappear from approved-for-cis endpoint."""
        tx = create_cis_ready_transaction(api_client, "WITHDRAW_DISAPPEAR")
        tx_id = tx["transaction_id"]
        
        try:
            api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
            
            # Verify it appears in approved-for-cis
            cis_resp1 = requests.get(f"{API_BASE}/approved-for-cis?target=TEST_CIS_WITHDRAW_DISAPPEAR")
            items1 = cis_resp1.json()["items"]
            assert any(i["id"] == tx_id for i in items1), "Should appear in approved-for-cis"
            
            # Withdraw
            api_client.post(f"{API_BASE}/{tx_id}/withdraw-from-cis", json={
                "reason": "out_of_scope"
            })
            
            # Verify it no longer appears
            cis_resp2 = requests.get(f"{API_BASE}/approved-for-cis?target=TEST_CIS_WITHDRAW_DISAPPEAR")
            items2 = cis_resp2.json()["items"]
            assert not any(i["id"] == tx_id for i in items2), "Should NOT appear in approved-for-cis after withdrawal"
            print("✓ Withdrawn transactions disappear from approved-for-cis endpoint")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")
    
    def test_withdraw_all_valid_reasons(self, api_client):
        """Test all valid withdrawal reasons work."""
        for reason in self.VALID_REASONS:
            tx = create_cis_ready_transaction(api_client, f"WITHDRAW_{reason[:8]}")
            tx_id = tx["transaction_id"]
            
            try:
                api_client.post(f"{API_BASE}/{tx_id}/approve-for-cis")
                
                withdraw_resp = api_client.post(f"{API_BASE}/{tx_id}/withdraw-from-cis", json={
                    "reason": reason
                })
                assert withdraw_resp.status_code == 200, f"Reason '{reason}' should be valid"
            finally:
                api_client.delete(f"{API_BASE}/{tx_id}")
        
        print(f"✓ All {len(self.VALID_REASONS)} withdrawal reasons work correctly")


# ═══════════════════════════════════════════════════════════════════════════════
# EXTERNAL ENTITY TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestExternalEntity:
    """Tests for POST /matching/{link_id}/external-entity endpoint."""
    
    def test_mark_external_entity(self, api_client):
        """POST /matching/{link_id}/external-entity marks entity as external."""
        # Create a transaction
        tx_data = {
            "target_name": "TEST_EXTERNAL_Target",
            "buyer_name": "TEST_EXTERNAL_Buyer",
            "announcement_date": "2025-06-15",
            "transaction_type": "takeover"
        }
        create_resp = api_client.post(API_BASE, json=tx_data)
        tx_id = create_resp.json()["transaction_id"]
        
        try:
            # Get the entity links
            get_resp = api_client.get(f"{API_BASE}/{tx_id}")
            tx = get_resp.json()
            links = tx.get("company_links", [])
            
            if links:
                link_id = links[0]["link_id"]
                
                # Mark as external
                ext_resp = api_client.post(f"{API_BASE}/matching/{link_id}/external-entity")
                assert ext_resp.status_code == 200
                assert ext_resp.json()["status"] == "external_entity"
                print(f"✓ POST /matching/{link_id}/external-entity marks entity as external")
            else:
                print("⚠ No entity links created for test transaction")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")
    
    def test_external_entity_does_not_block_cis(self, api_client):
        """External entity does not block CIS publication."""
        tx = create_cis_ready_transaction(api_client, "EXTERNAL_CIS")
        tx_id = tx["transaction_id"]
        
        try:
            # Validate for CIS (entity already marked as external in helper)
            validate_resp = api_client.post(f"{API_BASE}/{tx_id}/validate-for-cis")
            validation = validate_resp.json()
            
            # Should be able to approve
            assert validation["can_approve"] == True, f"Should be able to approve. Missing: {validation.get('missing_requirements')}"
            print("✓ External entity does not block CIS publication")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# APPROVED-FOR-CIS ENDPOINT TESTS (NEW FIELDS)
# ═══════════════════════════════════════════════════════════════════════════════

class TestApprovedForCISEndpoint:
    """Tests for GET /approved-for-cis with new fields."""
    
    def test_approved_for_cis_returns_primary_source(self):
        """GET /approved-for-cis returns primary_source object."""
        response = requests.get(f"{API_BASE}/approved-for-cis?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        if data["items"]:
            item = data["items"][0]
            assert "primary_source" in item, "Response should include primary_source"
            print(f"✓ GET /approved-for-cis returns primary_source: {item.get('primary_source')}")
        else:
            print("⚠ No approved transactions to test primary_source")
    
    def test_approved_for_cis_returns_sources_array(self):
        """GET /approved-for-cis returns sources[] array."""
        response = requests.get(f"{API_BASE}/approved-for-cis?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        if data["items"]:
            item = data["items"][0]
            assert "sources" in item, "Response should include sources array"
            assert isinstance(item["sources"], list)
            print(f"✓ GET /approved-for-cis returns sources array with {len(item['sources'])} items")
        else:
            print("⚠ No approved transactions to test sources array")
    
    def test_approved_for_cis_returns_summary(self):
        """GET /approved-for-cis returns summary field."""
        response = requests.get(f"{API_BASE}/approved-for-cis?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        if data["items"]:
            item = data["items"][0]
            assert "summary" in item, "Response should include summary"
            print(f"✓ GET /approved-for-cis returns summary field")
        else:
            print("⚠ No approved transactions to test summary")
    
    def test_approved_for_cis_returns_strategic_rationale(self):
        """GET /approved-for-cis returns strategic_rationale field."""
        response = requests.get(f"{API_BASE}/approved-for-cis?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        if data["items"]:
            item = data["items"][0]
            assert "strategic_rationale" in item, "Response should include strategic_rationale"
            print(f"✓ GET /approved-for-cis returns strategic_rationale field")
        else:
            print("⚠ No approved transactions to test strategic_rationale")
    
    def test_approved_for_cis_retrocompat_source_name(self):
        """GET /approved-for-cis retro-compat: source_name from primary_source.publisher."""
        response = requests.get(f"{API_BASE}/approved-for-cis?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        if data["items"]:
            item = data["items"][0]
            assert "source_name" in item, "Response should include source_name for retrocompatibility"
            assert "source_url" in item, "Response should include source_url for retrocompatibility"
            print(f"✓ GET /approved-for-cis retro-compat: source_name={item.get('source_name')}")
        else:
            print("⚠ No approved transactions to test retrocompat")


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW ENDPOINTS TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestViewEndpoints:
    """Tests for view endpoints (needs-review, ready-for-cis, published)."""
    
    def test_views_needs_review(self, api_client):
        """GET /views/needs-review returns transactions needing intervention."""
        response = api_client.get(f"{API_BASE}/views/needs-review?limit=10")
        assert response.status_code == 200
        data = response.json()
        
        assert "transactions" in data
        assert "total" in data
        assert isinstance(data["transactions"], list)
        
        # Each transaction should have visible_status and incidences
        for tx in data["transactions"]:
            assert "visible_status" in tx
            assert "incidences" in tx
            assert tx["visible_status"] in ["needs_review", "incomplete"]
        
        print(f"✓ GET /views/needs-review returns {data['total']} transactions")
    
    def test_views_ready_for_cis(self, api_client):
        """GET /views/ready-for-cis returns transactions ready to publish."""
        response = api_client.get(f"{API_BASE}/views/ready-for-cis?limit=10")
        assert response.status_code == 200
        data = response.json()
        
        assert "transactions" in data
        assert "total" in data
        assert isinstance(data["transactions"], list)
        
        # Each transaction should have visible_status = ready_for_cis
        for tx in data["transactions"]:
            assert "visible_status" in tx
            assert tx["visible_status"] == "ready_for_cis"
        
        print(f"✓ GET /views/ready-for-cis returns {data['total']} transactions")
    
    def test_views_published(self, api_client):
        """GET /views/published returns published transactions."""
        response = api_client.get(f"{API_BASE}/views/published?limit=10")
        assert response.status_code == 200
        data = response.json()
        
        assert "transactions" in data
        assert "total" in data
        assert isinstance(data["transactions"], list)
        
        # Each transaction should have visible_status in published states
        for tx in data["transactions"]:
            assert "visible_status" in tx
            assert tx["visible_status"] in ["published_in_cis", "pending_sync"]
        
        print(f"✓ GET /views/published returns {data['total']} transactions")
    
    def test_views_have_enriched_data(self, api_client):
        """View endpoints return enriched transaction data."""
        response = api_client.get(f"{API_BASE}/views/needs-review?limit=5")
        assert response.status_code == 200
        data = response.json()
        
        if data["transactions"]:
            tx = data["transactions"][0]
            # Check for enriched fields
            assert "visible_status" in tx
            assert "incidences" in tx
            assert "sources_count" in tx
            assert "primary_source_publisher" in tx
            print("✓ View endpoints return enriched transaction data")
        else:
            print("⚠ No transactions in needs-review to test enrichment")


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATE-FOR-CIS CHECKS SOURCES
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateForCISSources:
    """Tests for validate-for-cis checking sources and summary requirements."""
    
    def test_validate_checks_sources_requirement(self, api_client):
        """Validate-for-cis checks sources requirement."""
        tx_data = {
            "target_name": "TEST_VALIDATE_NoSource",
            "buyer_name": "TEST_VALIDATE_Buyer",
            "announcement_date": "2025-06-15",
            "transaction_type": "takeover",
            "geography_primary": "Spain",
            "cis_category_suggested": "Digital, Growth y Commerce",
            "summary": "Test summary"
            # No source or source_url
        }
        create_resp = api_client.post(API_BASE, json=tx_data)
        tx_id = create_resp.json()["transaction_id"]
        
        try:
            api_client.post(f"{API_BASE}/{tx_id}/review?status=approved")
            
            validate_resp = api_client.post(f"{API_BASE}/{tx_id}/validate-for-cis")
            validation = validate_resp.json()
            
            # Should have source-related missing requirement
            missing = validation.get("missing_requirements", [])
            has_source_missing = any("fuente" in m.lower() for m in missing)
            
            assert has_source_missing, f"Should require source. Missing: {missing}"
            print("✓ Validate-for-cis checks sources requirement")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")
    
    def test_validate_checks_summary_requirement(self, api_client):
        """Validate-for-cis checks summary requirement."""
        tx_data = {
            "target_name": "TEST_VALIDATE_NoSummary",
            "buyer_name": "TEST_VALIDATE_Buyer2",
            "announcement_date": "2025-06-15",
            "transaction_type": "takeover",
            "geography_primary": "Spain",
            "cis_category_suggested": "Digital, Growth y Commerce",
            "source": "Test Source"
            # No summary
        }
        create_resp = api_client.post(API_BASE, json=tx_data)
        tx_id = create_resp.json()["transaction_id"]
        
        try:
            api_client.post(f"{API_BASE}/{tx_id}/review?status=approved")
            
            validate_resp = api_client.post(f"{API_BASE}/{tx_id}/validate-for-cis")
            validation = validate_resp.json()
            
            # Should have summary-related missing requirement
            missing = validation.get("missing_requirements", [])
            has_summary_missing = any("descripcion" in m.lower() or "summary" in m.lower() for m in missing)
            
            assert has_summary_missing, f"Should require summary. Missing: {missing}"
            print("✓ Validate-for-cis checks summary requirement")
        finally:
            api_client.delete(f"{API_BASE}/{tx_id}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
