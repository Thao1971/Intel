"""
AI Classification Copilot Tests - Transaction Intelligence Module
Tests GPT-5.2 powered classification suggestions with accept/reject workflow.

Features tested:
- POST /api/v1/transactions/{tx_id}/suggest-classification generates a valid suggestion
- Suggestion response has requires_human_review=true always
- Suggestion is validated against CIS taxonomy (validation_status: valid or invalid)
- Suggestion is persisted in transaction_classification_suggestions collection
- GET /api/v1/transactions/{tx_id}/classification-suggestions returns suggestion history
- POST /api/v1/transactions/{tx_id}/classification-suggestions/{id}/accept applies category to transaction
- POST /api/v1/transactions/{tx_id}/classification-suggestions/{id}/reject marks as rejected without changing transaction
- Cannot accept an invalid suggestion (returns 400)
- Cannot accept an already accepted suggestion (returns 400)
- Accepting a suggestion marks previous suggestions as superseded
- Audit logs capture classification_suggested, classification_accepted, classification_rejected actions
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = "https://data-factory-hub.preview.emergentagent.com"

TEST_EMAIL = "daniel@wearebudadvisors.com"
TEST_PASSWORD = __import__("os").environ.get("SMOKE_TEST_PASSWORD", "")


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token."""
    response = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Shared requests session with auth header."""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


@pytest.fixture(scope="module")
def existing_transaction(api_client):
    """Get an existing transaction for testing."""
    response = api_client.get(f"{BASE_URL}/api/v1/transactions", params={"limit": 10})
    assert response.status_code == 200
    txs = response.json().get("transactions", [])
    if not txs:
        pytest.skip("No existing transactions found for testing")
    # Return first transaction
    return txs[0]


@pytest.fixture(scope="module")
def test_transaction(api_client):
    """Create a test transaction for classification testing."""
    tx_data = {
        "target_name": "TEST_ClassificationCopilot Agency",
        "buyer_name": "TEST_Buyer Corp",
        "announcement_date": "2026-01-15",
        "transaction_type": "takeover",
        "geography_primary": "Spain",
        "sector_original": "Advertising",
        "observations": "Digital marketing agency specializing in social media and content creation for brands.",
        "source": "Test"
    }
    response = api_client.post(f"{BASE_URL}/api/v1/transactions", json=tx_data)
    assert response.status_code == 200, f"Failed to create test transaction: {response.text}"
    tx = response.json()
    yield tx
    # Cleanup
    api_client.delete(f"{BASE_URL}/api/v1/transactions/{tx['transaction_id']}")


class TestClassificationSuggestionGeneration:
    """Tests for generating classification suggestions."""

    def test_suggest_classification_returns_valid_response(self, api_client, test_transaction):
        """POST /api/v1/transactions/{tx_id}/suggest-classification generates a valid suggestion."""
        tx_id = test_transaction["transaction_id"]
        
        # This endpoint calls GPT-5.2 which takes 5-10 seconds
        response = api_client.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/suggest-classification",
            timeout=60
        )
        
        assert response.status_code == 200, f"Failed to generate suggestion: {response.text}"
        data = response.json()
        
        # Verify required fields exist
        assert "suggestion_id" in data, "Missing suggestion_id"
        assert "transaction_id" in data, "Missing transaction_id"
        assert data["transaction_id"] == tx_id
        assert "suggested_category" in data, "Missing suggested_category"
        assert "suggested_subcategory" in data, "Missing suggested_subcategory"
        assert "confidence" in data, "Missing confidence"
        assert "confidence_label" in data, "Missing confidence_label"
        assert "reasoning" in data, "Missing reasoning"
        assert "signals_used" in data, "Missing signals_used"
        assert "validation_status" in data, "Missing validation_status"
        assert "status" in data, "Missing status"
        assert data["status"] == "suggested"
        
        print(f"Generated suggestion: {data['suggestion_id']}")
        print(f"Category: {data['suggested_category']} > {data['suggested_subcategory']}")
        print(f"Confidence: {data['confidence_label']} ({data['confidence']})")
        print(f"Validation: {data['validation_status']}")

    def test_suggestion_always_requires_human_review(self, api_client, test_transaction):
        """Suggestion response has requires_human_review=true always."""
        tx_id = test_transaction["transaction_id"]
        
        # Get existing suggestions
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions")
        assert response.status_code == 200
        suggestions = response.json().get("suggestions", [])
        
        if not suggestions:
            # Generate one if none exist
            response = api_client.post(
                f"{BASE_URL}/api/v1/transactions/{tx_id}/suggest-classification",
                timeout=60
            )
            assert response.status_code == 200
            data = response.json()
            assert data.get("requires_human_review") == True, "requires_human_review should always be True"
        else:
            # Check existing suggestion
            for sug in suggestions:
                assert sug.get("requires_human_review") == True, f"Suggestion {sug['suggestion_id']} should have requires_human_review=True"

    def test_suggestion_validated_against_taxonomy(self, api_client, test_transaction):
        """Suggestion is validated against CIS taxonomy (validation_status: valid or invalid)."""
        tx_id = test_transaction["transaction_id"]
        
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions")
        assert response.status_code == 200
        suggestions = response.json().get("suggestions", [])
        
        if not suggestions:
            pytest.skip("No suggestions available to validate")
        
        for sug in suggestions:
            assert "validation_status" in sug, "Missing validation_status"
            assert sug["validation_status"] in ["valid", "invalid"], f"Invalid validation_status: {sug['validation_status']}"
            
            if sug["validation_status"] == "invalid":
                assert "validation_errors" in sug, "Invalid suggestion should have validation_errors"
                print(f"Suggestion {sug['suggestion_id']} is invalid: {sug.get('validation_errors')}")
            else:
                print(f"Suggestion {sug['suggestion_id']} is valid")


class TestClassificationSuggestionPersistence:
    """Tests for suggestion persistence and retrieval."""

    def test_suggestion_persisted_in_collection(self, api_client, test_transaction):
        """Suggestion is persisted in transaction_classification_suggestions collection."""
        tx_id = test_transaction["transaction_id"]
        
        # Get suggestions
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions")
        assert response.status_code == 200
        suggestions = response.json().get("suggestions", [])
        
        # Should have at least one suggestion from previous tests
        assert len(suggestions) > 0, "No suggestions found - persistence failed"
        
        # Verify suggestion structure
        sug = suggestions[0]
        assert "suggestion_id" in sug
        assert "transaction_id" in sug
        assert "created_at" in sug
        assert "created_by" in sug
        print(f"Found {len(suggestions)} persisted suggestions")

    def test_get_classification_suggestions_returns_history(self, api_client, test_transaction):
        """GET /api/v1/transactions/{tx_id}/classification-suggestions returns suggestion history."""
        tx_id = test_transaction["transaction_id"]
        
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions")
        assert response.status_code == 200
        
        data = response.json()
        assert "suggestions" in data
        assert isinstance(data["suggestions"], list)
        
        # Suggestions should be sorted by created_at descending
        suggestions = data["suggestions"]
        if len(suggestions) > 1:
            for i in range(len(suggestions) - 1):
                assert suggestions[i]["created_at"] >= suggestions[i+1]["created_at"], "Suggestions not sorted by created_at desc"

    def test_suggestion_contains_model_info(self, api_client, test_transaction):
        """Suggestion contains model_used and prompt_version."""
        tx_id = test_transaction["transaction_id"]
        
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions")
        assert response.status_code == 200
        suggestions = response.json().get("suggestions", [])
        
        if not suggestions:
            pytest.skip("No suggestions available")
        
        sug = suggestions[0]
        assert "model_used" in sug, "Missing model_used"
        assert "openai/gpt-5.2" in sug["model_used"], f"Unexpected model: {sug['model_used']}"
        assert "prompt_version" in sug, "Missing prompt_version"
        print(f"Model: {sug['model_used']}, Prompt version: {sug['prompt_version']}")


class TestClassificationAcceptReject:
    """Tests for accept/reject workflow."""

    def test_accept_valid_suggestion_applies_to_transaction(self, api_client, test_transaction):
        """POST /api/v1/transactions/{tx_id}/classification-suggestions/{id}/accept applies category to transaction."""
        tx_id = test_transaction["transaction_id"]
        
        # Get suggestions
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions")
        assert response.status_code == 200
        suggestions = response.json().get("suggestions", [])
        
        # Find a valid, suggested (not yet accepted/rejected) suggestion
        valid_suggestion = None
        for sug in suggestions:
            if sug["validation_status"] == "valid" and sug["status"] == "suggested":
                valid_suggestion = sug
                break
        
        if not valid_suggestion:
            # Generate a new suggestion
            response = api_client.post(
                f"{BASE_URL}/api/v1/transactions/{tx_id}/suggest-classification",
                timeout=60
            )
            assert response.status_code == 200
            valid_suggestion = response.json()
            if valid_suggestion["validation_status"] != "valid":
                pytest.skip("Generated suggestion is invalid - cannot test accept")
        
        suggestion_id = valid_suggestion["suggestion_id"]
        expected_category = valid_suggestion["suggested_category"]
        expected_subcategory = valid_suggestion["suggested_subcategory"]
        
        # Accept the suggestion
        response = api_client.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions/{suggestion_id}/accept"
        )
        assert response.status_code == 200, f"Failed to accept suggestion: {response.text}"
        
        data = response.json()
        assert data["status"] == "accepted"
        assert data["category"] == expected_category
        assert data["subcategory"] == expected_subcategory
        
        # Verify transaction was updated
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}")
        assert response.status_code == 200
        tx = response.json()
        assert tx.get("cis_category_suggested") == expected_category, "Category not applied to transaction"
        assert tx.get("cis_subcategory_suggested") == expected_subcategory, "Subcategory not applied to transaction"
        assert tx.get("sector_mapping_status") == "approved", "sector_mapping_status not set to approved"
        
        print(f"Accepted suggestion {suggestion_id}")
        print(f"Transaction updated: {expected_category} > {expected_subcategory}")

    def test_reject_suggestion_does_not_change_transaction(self, api_client, test_transaction):
        """POST /api/v1/transactions/{tx_id}/classification-suggestions/{id}/reject marks as rejected without changing transaction."""
        tx_id = test_transaction["transaction_id"]
        
        # Get current transaction state
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}")
        assert response.status_code == 200
        tx_before = response.json()
        
        # Generate a new suggestion to reject
        response = api_client.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/suggest-classification",
            timeout=60
        )
        assert response.status_code == 200
        suggestion = response.json()
        suggestion_id = suggestion["suggestion_id"]
        
        # Reject the suggestion
        response = api_client.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions/{suggestion_id}/reject"
        )
        assert response.status_code == 200, f"Failed to reject suggestion: {response.text}"
        
        data = response.json()
        assert data["status"] == "rejected"
        
        # Verify suggestion status changed
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions")
        assert response.status_code == 200
        suggestions = response.json().get("suggestions", [])
        rejected_sug = next((s for s in suggestions if s["suggestion_id"] == suggestion_id), None)
        assert rejected_sug is not None
        assert rejected_sug["status"] == "rejected"
        assert rejected_sug.get("rejected_by") is not None
        assert rejected_sug.get("rejected_at") is not None
        
        # Verify transaction was NOT changed (category should remain from previous accept)
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}")
        assert response.status_code == 200
        tx_after = response.json()
        assert tx_after.get("cis_category_suggested") == tx_before.get("cis_category_suggested"), "Transaction category changed after reject"
        
        print(f"Rejected suggestion {suggestion_id} - transaction unchanged")

    def test_cannot_accept_invalid_suggestion(self, api_client, test_transaction):
        """Cannot accept an invalid suggestion (returns 400)."""
        tx_id = test_transaction["transaction_id"]
        
        # Get suggestions
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions")
        assert response.status_code == 200
        suggestions = response.json().get("suggestions", [])
        
        # Find an invalid suggestion
        invalid_suggestion = None
        for sug in suggestions:
            if sug["validation_status"] == "invalid" and sug["status"] == "suggested":
                invalid_suggestion = sug
                break
        
        if not invalid_suggestion:
            pytest.skip("No invalid suggestions available to test")
        
        suggestion_id = invalid_suggestion["suggestion_id"]
        
        # Try to accept invalid suggestion
        response = api_client.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions/{suggestion_id}/accept"
        )
        assert response.status_code == 400, f"Should return 400 for invalid suggestion, got {response.status_code}"
        print(f"Correctly rejected acceptance of invalid suggestion {suggestion_id}")

    def test_cannot_accept_already_accepted_suggestion(self, api_client, test_transaction):
        """Cannot accept an already accepted suggestion (returns 400)."""
        tx_id = test_transaction["transaction_id"]
        
        # Get suggestions
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions")
        assert response.status_code == 200
        suggestions = response.json().get("suggestions", [])
        
        # Find an already accepted suggestion
        accepted_suggestion = None
        for sug in suggestions:
            if sug["status"] == "accepted":
                accepted_suggestion = sug
                break
        
        if not accepted_suggestion:
            pytest.skip("No accepted suggestions available to test")
        
        suggestion_id = accepted_suggestion["suggestion_id"]
        
        # Try to accept again
        response = api_client.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions/{suggestion_id}/accept"
        )
        assert response.status_code == 400, f"Should return 400 for already accepted suggestion, got {response.status_code}"
        assert "already" in response.text.lower(), f"Error message should mention 'already': {response.text}"
        print(f"Correctly rejected re-acceptance of suggestion {suggestion_id}")

    def test_accepting_marks_previous_as_superseded(self, api_client, test_transaction):
        """Accepting a suggestion marks previous suggestions as superseded."""
        tx_id = test_transaction["transaction_id"]
        
        # Generate two new suggestions
        response = api_client.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/suggest-classification",
            timeout=60
        )
        assert response.status_code == 200
        sug1 = response.json()
        
        time.sleep(1)  # Small delay to ensure different timestamps
        
        response = api_client.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/suggest-classification",
            timeout=60
        )
        assert response.status_code == 200
        sug2 = response.json()
        
        # Accept the second suggestion (if valid)
        if sug2["validation_status"] == "valid":
            response = api_client.post(
                f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions/{sug2['suggestion_id']}/accept"
            )
            assert response.status_code == 200
            
            # Check that first suggestion is now superseded
            response = api_client.get(f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions")
            assert response.status_code == 200
            suggestions = response.json().get("suggestions", [])
            
            sug1_updated = next((s for s in suggestions if s["suggestion_id"] == sug1["suggestion_id"]), None)
            if sug1_updated and sug1_updated["status"] == "suggested":
                # Should be superseded
                assert sug1_updated["status"] == "superseded", f"Previous suggestion should be superseded, got {sug1_updated['status']}"
                print(f"Previous suggestion {sug1['suggestion_id']} correctly marked as superseded")
        else:
            pytest.skip("Second suggestion is invalid - cannot test supersede")


class TestClassificationAuditLogs:
    """Tests for audit logging of classification actions."""

    def test_audit_log_classification_suggested(self, api_client, test_transaction):
        """Audit logs capture classification_suggested action."""
        tx_id = test_transaction["transaction_id"]
        
        # Get audit logs
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/audit/{tx_id}")
        assert response.status_code == 200
        logs = response.json().get("logs", [])
        
        # Find classification_suggested action
        suggested_logs = [l for l in logs if l["action"] == "classification_suggested"]
        assert len(suggested_logs) > 0, "No classification_suggested audit logs found"
        
        log = suggested_logs[0]
        assert "changed_by" in log
        assert "changed_at" in log
        assert "new_values" in log
        assert "suggestion_id" in log["new_values"]
        print(f"Found {len(suggested_logs)} classification_suggested audit logs")

    def test_audit_log_classification_accepted(self, api_client, test_transaction):
        """Audit logs capture classification_accepted action."""
        tx_id = test_transaction["transaction_id"]
        
        # Get audit logs
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/audit/{tx_id}")
        assert response.status_code == 200
        logs = response.json().get("logs", [])
        
        # Find classification_accepted action
        accepted_logs = [l for l in logs if l["action"] == "classification_accepted"]
        assert len(accepted_logs) > 0, "No classification_accepted audit logs found"
        
        log = accepted_logs[0]
        assert "changed_by" in log
        assert "changed_at" in log
        assert "new_values" in log
        assert "category" in log["new_values"]
        assert "subcategory" in log["new_values"]
        print(f"Found {len(accepted_logs)} classification_accepted audit logs")

    def test_audit_log_classification_rejected(self, api_client, test_transaction):
        """Audit logs capture classification_rejected action."""
        tx_id = test_transaction["transaction_id"]
        
        # Get audit logs
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/audit/{tx_id}")
        assert response.status_code == 200
        logs = response.json().get("logs", [])
        
        # Find classification_rejected action
        rejected_logs = [l for l in logs if l["action"] == "classification_rejected"]
        assert len(rejected_logs) > 0, "No classification_rejected audit logs found"
        
        log = rejected_logs[0]
        assert "changed_by" in log
        assert "changed_at" in log
        assert "new_values" in log
        assert "suggestion_id" in log["new_values"]
        print(f"Found {len(rejected_logs)} classification_rejected audit logs")


class TestClassificationEdgeCases:
    """Tests for edge cases and error handling."""

    def test_suggest_classification_nonexistent_transaction(self, api_client):
        """Suggest classification for nonexistent transaction returns 404."""
        response = api_client.post(
            f"{BASE_URL}/api/v1/transactions/tx_nonexistent123/suggest-classification",
            timeout=30
        )
        assert response.status_code == 404

    def test_accept_nonexistent_suggestion(self, api_client, test_transaction):
        """Accept nonexistent suggestion returns 404."""
        tx_id = test_transaction["transaction_id"]
        response = api_client.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions/sug_nonexistent/accept"
        )
        assert response.status_code == 404

    def test_reject_nonexistent_suggestion(self, api_client, test_transaction):
        """Reject nonexistent suggestion returns 404."""
        tx_id = test_transaction["transaction_id"]
        response = api_client.post(
            f"{BASE_URL}/api/v1/transactions/{tx_id}/classification-suggestions/sug_nonexistent/reject"
        )
        assert response.status_code == 404

    def test_get_suggestions_nonexistent_transaction(self, api_client):
        """Get suggestions for nonexistent transaction returns empty list or 404."""
        response = api_client.get(
            f"{BASE_URL}/api/v1/transactions/tx_nonexistent123/classification-suggestions"
        )
        # Could return 200 with empty list or 404
        if response.status_code == 200:
            assert response.json().get("suggestions", []) == []
        else:
            assert response.status_code == 404


class TestGlobalAuditLogFiltering:
    """Tests for global audit log with classification actions."""

    def test_global_audit_shows_classification_actions(self, api_client):
        """Global audit log includes classification actions."""
        response = api_client.get(f"{BASE_URL}/api/v1/transactions/audit-global", params={"limit": 100})
        assert response.status_code == 200
        logs = response.json().get("logs", [])
        
        classification_actions = ["classification_suggested", "classification_accepted", "classification_rejected"]
        found_actions = set()
        
        for log in logs:
            if log["action"] in classification_actions:
                found_actions.add(log["action"])
        
        print(f"Found classification actions in global audit: {found_actions}")
        # At least one classification action should exist from our tests
        assert len(found_actions) > 0, "No classification actions found in global audit log"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
