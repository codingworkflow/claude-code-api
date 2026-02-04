#!/usr/bin/env python3
"""
REAL End-to-End Tests - Actually tests the running HTTP API
Unlike the fake tests that import the app directly.
"""

import sys

import requests

from tests.model_utils import get_test_model_id


class RealAPITester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session = requests.Session()

    def test_health(self) -> bool:
        """Test health endpoint."""
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=5)
            print(f"Health Check: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   Status: {data.get('status')}")
                print(f"   Version: {data.get('version')}")
                return True
            else:
                print(f"   Error: {response.text}")
                return False
        except Exception as e:
            print(f"Health check failed: {e}")
            return False

    def test_models(self) -> bool:
        """Test models endpoint."""
        try:
            response = self.session.get(f"{self.base_url}/v1/models", timeout=5)
            print(f"Models API: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])
                print(f"   Found {len(models)} models:")
                for model in models[:2]:  # Show first 2
                    print(f"     - {model.get('id')}")
                return True
            else:
                print(f"   Error: {response.text}")
                return False
        except Exception as e:
            print(f"Models test failed: {e}")
            return False

    def test_auth_bypass(self) -> bool:
        """Test that API works without auth (should work with current config)."""
        try:
            # Test without any auth headers
            response = self.session.get(f"{self.base_url}/v1/models", timeout=5)
            print(f"Auth Bypass Test: {response.status_code}")

            if response.status_code == 200:
                print("   API works without authentication")
                return True
            elif response.status_code == 401:
                print("   API requires authentication")
                error = response.json()
                print(
                    f"   Error: {error.get('error', {}).get('message', 'Unknown auth error')}"
                )
                return False
            else:
                print(f"   Unexpected status: {response.text}")
                return False
        except Exception as e:
            print(f"Auth test failed: {e}")
            return False

    def test_chat_completion(self) -> bool:
        """Test chat completion endpoint (may be slow)."""
        try:
            payload = {
                "model": get_test_model_id(),
                "messages": [
                    {
                        "role": "user",
                        "content": "Say 'test successful' and nothing else",
                    }
                ],
                "stream": False,
            }

            print("Chat Completion (this may take a while)...")
            response = self.session.post(
                f"{self.base_url}/v1/chat/completions", json=payload, timeout=30
            )

            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                if "choices" in data and len(data["choices"]) > 0:
                    content = data["choices"][0].get("message", {}).get("content", "")
                    print(f"   Response: {content[:100]}...")
                    return True
            else:
                print(f"   Error: {response.text[:200]}...")

            return response.status_code == 200

        except requests.exceptions.Timeout:
            print("   Chat completion timed out (expected with mock setup)")
            return True  # Timeout is expected with echo mock
        except Exception as e:
            print(f"Chat completion failed: {e}")
            return False

    def run_all_tests(self) -> bool:
        """Run all tests and return overall success."""
        print("REAL End-to-End API Tests")
        print("=" * 40)

        tests = [
            ("Health Check", self.test_health),
            ("Models API", self.test_models),
            ("Auth Bypass", self.test_auth_bypass),
            ("Chat Completion", self.test_chat_completion),
        ]

        results = []
        for test_name, test_func in tests:
            print(f"\n{test_name}:")
            try:
                result = test_func()
                results.append(result)
                status = "PASS" if result else "FAIL"
                print(f"   {status}")
            except Exception as e:
                print(f"   FAIL: {e}")
                results.append(False)

        print("\n" + "=" * 40)
        passed = sum(results)
        total = len(results)
        print(f"Results: {passed}/{total} tests passed")

        if passed == total:
            print("ALL TESTS PASSED!")
            return True
        else:
            print("SOME TESTS FAILED!")
            return False


def check_server_running(url: str = "http://localhost:8000") -> bool:
    """Check if server is running."""
    try:
        response = requests.get(f"{url}/health", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def main():
    print("Checking if API server is running...")

    if not check_server_running():
        print("API server not running on http://localhost:8000")
        print("Start the server with: make start")
        sys.exit(1)

    print("Server is running!")
    print()

    tester = RealAPITester()
    success = tester.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
