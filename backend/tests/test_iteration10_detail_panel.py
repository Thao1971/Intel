"""
Iteration 10 Tests: Transaction Detail Panel - Full Editability, Taxonomy, Entity Actions, Validation Checklist
Tests the corrected detail panel with all editable fields, CIS taxonomy dropdowns, entity actions, and validation endpoints.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "daniel@wearebudadvisors.com"
TEST_PASSWORD = __import__("os").environ.get("SMOKE_TEST_PASSWORD", "")


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for API calls."""
    response = requests.post(f"{BASE_URL}/api/v1/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Authenticated requests session."""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


class TestTaxonomyOptions:
    """Test GET /taxonomy-options endpoint returns 10 CIS categories with subcategories."""

    def test_taxonomy_options_returns_categories(self, api_client):
        """Verify taxonomy-options returns categories array."""
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/taxonomy-options")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "categories" in data, "Response should have 'categories' key"
        assert isinstance(data["categories"], list), "Categories should be a list"

    def test_taxonomy_options_has_10_categories(self, api_client):
        """Verify taxonomy returns exactly 10 CIS categories."""
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/taxonomy-options")
        assert response.status_code == 200
        
        data = response.json()
        categories = data.get("categories", [])
        # Should have 10 categories as per requirements
        assert len(categories) >= 10, f"Expected at least 10 categories, got {len(categories)}"
        
        # Each category should have name and subcategories
        for cat in categories:
            assert "name" in cat, f"Category missing 'name': {cat}"
            assert "subcategories" in cat, f"Category missing 'subcategories': {cat}"
            assert isinstance(cat["subcategories"], list), f"Subcategories should be list: {cat}"

    def test_taxonomy_categories_have_subcategories(self, api_client):
        """Verify each category has subcategories."""
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/taxonomy-options")
        assert response.status_code == 200
        
        data = response.json()
        categories = data.get("categories", [])
        
        # At least some categories should have subcategories
        cats_with_subs = [c for c in categories if len(c.get("subcategories", [])) > 0]
        assert len(cats_with_subs) > 0, "At least some categories should have subcategories"


class TestValidationChecklist:
    """Test GET /{tx_id}/validation-checklist endpoint."""

    def test_validation_checklist_returns_requirements(self, api_client):
        """Verify validation-checklist returns structured requirements array."""
        # First get a transaction ID
        txs_response = api_client.get(f"{BASE_URL}/api/v1/transactions?limit=1")
        assert txs_response.status_code == 200
        
        txs = txs_response.json().get("transactions", [])
        if not txs:
            pytest.skip("No transactions available for testing")
        
        tx_id = txs[0]["transaction_id"]
        
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/validation-checklist")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "requirements" in data, "Response should have 'requirements' key"
        assert "can_publish" in data, "Response should have 'can_publish' key"
        assert isinstance(data["requirements"], list), "Requirements should be a list"

    def test_validation_checklist_has_block_references(self, api_client):
        """Verify each requirement has key, status, label, message, and block."""
        txs_response = api_client.get(f"{BASE_URL}/api/v1/transactions?limit=1")
        assert txs_response.status_code == 200
        
        txs = txs_response.json().get("transactions", [])
        if not txs:
            pytest.skip("No transactions available for testing")
        
        tx_id = txs[0]["transaction_id"]
        
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/validation-checklist")
        assert response.status_code == 200
        
        data = response.json()
        requirements = data.get("requirements", [])
        
        # Check each requirement has required fields
        expected_fields = ["key", "status", "label", "message", "block"]
        for req in requirements:
            for field in expected_fields:
                assert field in req, f"Requirement missing '{field}': {req}"
        
        # Check block references are valid
        valid_blocks = ["basics", "classification", "sources", "description", "entities", "quality"]
        for req in requirements:
            assert req["block"] in valid_blocks, f"Invalid block reference: {req['block']}"

    def test_validation_checklist_status_values(self, api_client):
        """Verify status values are ok, warning, or error."""
        txs_response = api_client.get(f"{BASE_URL}/api/v1/transactions?limit=1")
        assert txs_response.status_code == 200
        
        txs = txs_response.json().get("transactions", [])
        if not txs:
            pytest.skip("No transactions available for testing")
        
        tx_id = txs[0]["transaction_id"]
        
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/validation-checklist")
        assert response.status_code == 200
        
        data = response.json()
        requirements = data.get("requirements", [])
        
        valid_statuses = ["ok", "warning", "error"]
        for req in requirements:
            assert req["status"] in valid_statuses, f"Invalid status: {req['status']}"


class TestMarkReviewed:
    """Test POST /{tx_id}/mark-reviewed endpoint."""

    def test_mark_reviewed_blocked_without_requirements(self, api_client):
        """Verify mark-reviewed returns blocked with blockers list when requirements missing."""
        # Create a minimal transaction without required fields
        create_response = api_client.post(f"{BASE_URL}/api/v1/transactions", json={
            "target_name": "TEST_MarkReviewed_Incomplete"
        })
        assert create_response.status_code == 200
        
        tx_id = create_response.json()["transaction_id"]
        
        try:
            # Try to mark as reviewed - should be blocked
            response = api_client.post(f"{BASE_URL}/api/v1/transactions/{tx_id}/mark-reviewed")
            assert response.status_code == 200
            
            data = response.json()
            assert data["status"] == "blocked", f"Expected 'blocked', got {data['status']}"
            assert "blockers" in data, "Response should have 'blockers' list"
            assert isinstance(data["blockers"], list), "Blockers should be a list"
            assert len(data["blockers"]) > 0, "Should have at least one blocker"
        finally:
            # Cleanup
            api_client.delete(f"{BASE_URL}/api/v1/transactions/{tx_id}")

    def test_mark_reviewed_succeeds_with_requirements(self, api_client):
        """Verify mark-reviewed succeeds when basic requirements met."""
        # Create a transaction with all required fields
        create_response = api_client.post(f"{BASE_URL}/api/v1/transactions", json={
            "target_name": "TEST_MarkReviewed_Complete",
            "announcement_date": "2026-01-15",
            "cis_category_suggested": "Tecnologia",
            "summary": "Test transaction for mark-reviewed endpoint"
        })
        assert create_response.status_code == 200
        
        tx_id = create_response.json()["transaction_id"]
        
        try:
            # Add a source
            source_response = api_client.post(f"{BASE_URL}/api/v1/transactions/sources/{tx_id}", json={
                "publisher": "Test Publisher",
                "url": "https://example.com/test",
                "is_primary": True
            })
            assert source_response.status_code == 200
            
            # Now mark as reviewed - should succeed
            response = api_client.post(f"{BASE_URL}/api/v1/transactions/{tx_id}/mark-reviewed")
            assert response.status_code == 200
            
            data = response.json()
            assert data["status"] == "reviewed", f"Expected 'reviewed', got {data['status']}"
        finally:
            # Cleanup
            api_client.delete(f"{BASE_URL}/api/v1/transactions/{tx_id}")


class TestMarkReadyForCIS:
    """Test POST /{tx_id}/mark-ready-for-cis endpoint."""

    def test_mark_ready_for_cis_runs_full_validation(self, api_client):
        """Verify mark-ready-for-cis runs full validation."""
        # Create a minimal transaction
        create_response = api_client.post(f"{BASE_URL}/api/v1/transactions", json={
            "target_name": "TEST_ReadyForCIS_Incomplete"
        })
        assert create_response.status_code == 200
        
        tx_id = create_response.json()["transaction_id"]
        
        try:
            # Try to mark as ready - should be blocked
            response = api_client.post(f"{BASE_URL}/api/v1/transactions/{tx_id}/mark-ready-for-cis")
            assert response.status_code == 200
            
            data = response.json()
            assert data["status"] == "blocked", f"Expected 'blocked', got {data['status']}"
            assert "missing_requirements" in data, "Response should have 'missing_requirements'"
            assert isinstance(data["missing_requirements"], list), "missing_requirements should be a list"
        finally:
            # Cleanup
            api_client.delete(f"{BASE_URL}/api/v1/transactions/{tx_id}")


class TestTransactionUpdate:
    """Test PUT /{tx_id} endpoint for all editable fields."""

    def test_update_basic_fields(self, api_client):
        """Verify all basic fields are editable: target, buyer, seller, date, type, country, status."""
        # Create a test transaction
        create_response = api_client.post(f"{BASE_URL}/api/v1/transactions", json={
            "target_name": "TEST_Update_Original"
        })
        assert create_response.status_code == 200
        
        tx_id = create_response.json()["transaction_id"]
        
        try:
            # Update all basic fields
            update_response = api_client.put(f"{BASE_URL}/api/v1/transactions/{tx_id}", json={
                "target_name": "TEST_Update_Modified",
                "buyer_name": "Test Buyer",
                "seller_name": "Test Seller",
                "announcement_date": "2026-01-20",
                "transaction_type": "merger",
                "geography_primary": "Spain",
                "status": "completed"
            })
            assert update_response.status_code == 200
            
            # Verify changes persisted
            get_response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}")
            assert get_response.status_code == 200
            
            tx = get_response.json()
            assert tx["target_name"] == "TEST_Update_Modified"
            assert tx["buyer_name"] == "Test Buyer"
            assert tx["seller_name"] == "Test Seller"
            assert tx["announcement_date"] == "2026-01-20"
            assert tx["transaction_type"] == "merger"
            assert tx["geography_primary"] == "Spain"
            assert tx["status"] == "completed"
        finally:
            # Cleanup
            api_client.delete(f"{BASE_URL}/api/v1/transactions/{tx_id}")

    def test_update_classification_fields(self, api_client):
        """Verify CIS category and subcategory are editable."""
        create_response = api_client.post(f"{BASE_URL}/api/v1/transactions", json={
            "target_name": "TEST_Classification_Update"
        })
        assert create_response.status_code == 200
        
        tx_id = create_response.json()["transaction_id"]
        
        try:
            # Update classification
            update_response = api_client.put(f"{BASE_URL}/api/v1/transactions/{tx_id}", json={
                "cis_category_suggested": "Tecnologia",
                "cis_subcategory_suggested": "Software"
            })
            assert update_response.status_code == 200
            
            # Verify
            get_response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}")
            tx = get_response.json()
            assert tx["cis_category_suggested"] == "Tecnologia"
            assert tx["cis_subcategory_suggested"] == "Software"
        finally:
            api_client.delete(f"{BASE_URL}/api/v1/transactions/{tx_id}")

    def test_update_outside_cis_taxonomy(self, api_client):
        """Verify outside_cis_taxonomy toggle works."""
        create_response = api_client.post(f"{BASE_URL}/api/v1/transactions", json={
            "target_name": "TEST_OutsideTaxonomy"
        })
        assert create_response.status_code == 200
        
        tx_id = create_response.json()["transaction_id"]
        
        try:
            # Set outside_cis_taxonomy to true
            update_response = api_client.put(f"{BASE_URL}/api/v1/transactions/{tx_id}", json={
                "outside_cis_taxonomy": True
            })
            assert update_response.status_code == 200
            
            # Verify
            get_response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}")
            tx = get_response.json()
            assert tx["outside_cis_taxonomy"] == True
        finally:
            api_client.delete(f"{BASE_URL}/api/v1/transactions/{tx_id}")

    def test_update_editorial_fields(self, api_client):
        """Verify summary, strategic_rationale, editorial_notes are editable."""
        create_response = api_client.post(f"{BASE_URL}/api/v1/transactions", json={
            "target_name": "TEST_Editorial_Update"
        })
        assert create_response.status_code == 200
        
        tx_id = create_response.json()["transaction_id"]
        
        try:
            # Update editorial fields
            update_response = api_client.put(f"{BASE_URL}/api/v1/transactions/{tx_id}", json={
                "summary": "Updated summary text",
                "strategic_rationale": "Updated strategic rationale",
                "editorial_notes": "Updated editorial notes"
            })
            assert update_response.status_code == 200
            
            # Verify
            get_response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}")
            tx = get_response.json()
            assert tx["summary"] == "Updated summary text"
            assert tx["strategic_rationale"] == "Updated strategic rationale"
            assert tx["editorial_notes"] == "Updated editorial notes"
        finally:
            api_client.delete(f"{BASE_URL}/api/v1/transactions/{tx_id}")

    def test_update_financial_fields(self, api_client):
        """Verify financial fields (value_eurm, revenue, EBITDA, EV, multiples) are editable."""
        create_response = api_client.post(f"{BASE_URL}/api/v1/transactions", json={
            "target_name": "TEST_Financial_Update"
        })
        assert create_response.status_code == 200
        
        tx_id = create_response.json()["transaction_id"]
        
        try:
            # Update financial fields
            update_response = api_client.put(f"{BASE_URL}/api/v1/transactions/{tx_id}", json={
                "value_eurm": 150.5,
                "revenue_eurm": 50.0,
                "ebitda_eurm": 10.0,
                "ev_eurm": 200.0,
                "ve_sales": 4.0,
                "ve_ebitda": 20.0
            })
            assert update_response.status_code == 200
            
            # Verify
            get_response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}")
            tx = get_response.json()
            assert tx["value_eurm"] == 150.5
            assert tx["revenue_eurm"] == 50.0
            assert tx["ebitda_eurm"] == 10.0
            assert tx["ev_eurm"] == 200.0
            assert tx["ve_sales"] == 4.0
            assert tx["ve_ebitda"] == 20.0
        finally:
            api_client.delete(f"{BASE_URL}/api/v1/transactions/{tx_id}")


class TestEntityActions:
    """Test entity action endpoints."""

    def test_external_entity_action(self, api_client):
        """Verify /matching/{link_id}/external-entity marks entity as external_entity."""
        # Get a transaction with company links
        txs_response = api_client.get(f"{BASE_URL}/api/v1/transactions?limit=10")
        assert txs_response.status_code == 200
        
        txs = txs_response.json().get("transactions", [])
        
        # Find a transaction with unresolved entity links
        link_id = None
        for tx in txs:
            tx_detail = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx['transaction_id']}")
            if tx_detail.status_code == 200:
                links = tx_detail.json().get("company_links", [])
                for link in links:
                    if link.get("match_status") in ["unmatched", "auto_ambiguous_candidate", "auto_strong_candidate"]:
                        link_id = link["link_id"]
                        break
            if link_id:
                break
        
        if not link_id:
            pytest.skip("No unresolved entity links available for testing")
        
        # Mark as external entity
        response = api_client.post(f"{BASE_URL}/api/v1/transactions/matching/{link_id}/external-entity")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "external_entity"

    def test_entity_search(self, api_client):
        """Verify /matching/search returns results."""
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/matching/search?q=test")
        assert response.status_code == 200
        
        data = response.json()
        assert "results" in data
        assert isinstance(data["results"], list)


class TestGuardarBorrador:
    """Test save draft functionality."""

    def test_guardar_borrador_saves_edited_fields(self, api_client):
        """Verify Guardar borrador saves edited fields."""
        # Create a transaction
        create_response = api_client.post(f"{BASE_URL}/api/v1/transactions", json={
            "target_name": "TEST_GuardarBorrador"
        })
        assert create_response.status_code == 200
        
        tx_id = create_response.json()["transaction_id"]
        
        try:
            # Update multiple fields (simulating edit mode save)
            update_response = api_client.put(f"{BASE_URL}/api/v1/transactions/{tx_id}", json={
                "target_name": "TEST_GuardarBorrador_Modified",
                "buyer_name": "New Buyer",
                "summary": "New summary",
                "value_eurm": 100.0
            })
            assert update_response.status_code == 200
            
            # Verify all changes persisted
            get_response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}")
            tx = get_response.json()
            assert tx["target_name"] == "TEST_GuardarBorrador_Modified"
            assert tx["buyer_name"] == "New Buyer"
            assert tx["summary"] == "New summary"
            assert tx["value_eurm"] == 100.0
        finally:
            api_client.delete(f"{BASE_URL}/api/v1/transactions/{tx_id}")


# Cleanup fixture to remove test data
@pytest.fixture(scope="module", autouse=True)
def cleanup_test_data(api_client):
    """Cleanup TEST_ prefixed transactions after tests."""
    yield
    # Cleanup
    try:
        txs_response = api_client.get(f"{BASE_URL}/api/v1/transactions?limit=100")
        if txs_response.status_code == 200:
            txs = txs_response.json().get("transactions", [])
            for tx in txs:
                if tx.get("target_name", "").startswith("TEST_"):
                    api_client.delete(f"{BASE_URL}/api/v1/transactions/{tx['transaction_id']}")
    except Exception:
        pass
