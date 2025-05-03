"""Basic Locust file for performance testing the Alatar API.

To run:
1. Ensure Locust is installed (`poetry install --with dev`).
2. Run locust -f performance_tests/locustfile.py
3. Open your browser to http://localhost:8089 (or the port specified by Locust).
4. Configure the number of users, spawn rate, and host (e.g., http://localhost:8000).
5. Start Swarming.
"""

import random
import time

from locust import HttpUser, between, events, task


@events.init_command_line_parser.add_listener
def _(parser):
    # Add command-line options for username and password
    parser.add_argument(
        "--test-username",
        type=str,
        env_var="LOCUST_TEST_USERNAME",
        default="testuser@example.com",
        help="Username for login",
    )
    parser.add_argument(
        "--test-password",
        type=str,
        env_var="LOCUST_TEST_PASSWORD",
        default="password",
        help="Password for login",
    )


class ApiUser(HttpUser):
    # Wait time between tasks executed by each user
    wait_time = between(1, 3)  # seconds
    token = None
    graphql_endpoint = "/graphql"
    # Store IDs created during the test run
    analysis_request_ids = []
    proposed_action_ids = []  # Requires actions to be created by analysis or fixtures

    def on_start(self):
        """Login the user when the test starts."""
        self.login()

    def login(self):
        """Authenticate and store the token."""
        # Use credentials from command line args or defaults
        username = self.environment.parsed_options.test_username
        password = self.environment.parsed_options.test_password

        login_mutation = """
            mutation Login($email: String!, $password: String!) {
                login(email: $email, password: $password) {
                    token
                    user {
                        id
                        email
                    }
                    userErrors { message field }
                }
            }
        """
        variables = {"email": username, "password": password}
        try:
            with self.client.post(
                self.graphql_endpoint,
                json={"query": login_mutation, "variables": variables},
                catch_response=True,
                name="Auth: Login",
            ) as response:
                if response.status_code == 200:
                    data = response.json()
                    if data.get("errors"):
                        response.failure(
                            f"GraphQL error during login: {data['errors']}"
                        )
                        return
                    login_data = data.get("data", {}).get("login")
                    if login_data and not login_data.get("userErrors"):
                        self.token = login_data.get("token")
                        if self.token:
                            response.success()
                            print(f"User {username} logged in successfully.")
                            # Set token for subsequent requests for this user
                            self.client.headers["Authorization"] = (
                                f"Bearer {self.token}"
                            )
                        else:
                            response.failure("Login successful but no token received")
                    else:
                        user_errors = (
                            login_data.get("userErrors") if login_data else "N/A"
                        )
                        response.failure(
                            f"Login failed with user errors: {user_errors}"
                        )
                else:
                    response.failure(
                        f"Login failed with status {response.status_code}: {response.text}"
                    )
        except Exception as e:
            # Mark as failure without using response object if request itself failed
            events.request.fire(
                request_type="POST",
                name="Auth: Login",
                response_time=0,
                response_length=0,
                exception=e,
                context=self.environment.parsed_options,  # Pass context
            )
            print(f"Exception during login for {username}: {e}")

    @task(1)
    def health_check(self):
        # Health check might not require auth, adjust if needed
        self.client.get("/_health", name="App: Health Check")

    @task(5)  # Higher weight: Simulate users submitting analyses
    def submit_analysis(self):
        if not self.token:
            print("User not logged in, skipping submit_analysis")
            self.login()  # Attempt login again
            return

        submit_mutation = """
            mutation Submit($prompt: String!) {
                submitAnalysisRequest(input: { prompt: $prompt }) {
                    analysisRequest { id status }
                    userErrors { message field }
                }
            }
        """
        prompt = f"Locust test analysis - {time.time()}"
        variables = {"prompt": prompt}
        with (
            self.client.post(
                self.graphql_endpoint,
                json={"query": submit_mutation, "variables": variables},
                catch_response=True,  # Use catch_response for manual success/failure reporting
                name="GraphQL: Submit Analysis",
                # No headers needed here as self.client.headers is set after login
            ) as response
        ):
            if response.status_code == 200:
                data = response.json()
                if data.get("errors"):
                    response.failure(
                        f"GraphQL error submitting analysis: {data['errors']}"
                    )
                elif (
                    data.get("data", {})
                    .get("submitAnalysisRequest", {})
                    .get("userErrors")
                ):
                    errors = data["data"]["submitAnalysisRequest"]["userErrors"]
                    response.failure(f"User errors submitting analysis: {errors}")
                else:
                    request_id = (
                        data.get("data", {})
                        .get("submitAnalysisRequest", {})
                        .get("analysisRequest", {})
                        .get("id")
                    )
                    if request_id:
                        self.analysis_request_ids.append(request_id)
                    response.success()
            else:
                response.failure(
                    f"Submit analysis failed with status {response.status_code}: {response.text}"
                )

    @task(3)  # Medium weight: Simulate users checking results
    def list_analysis_requests(self):
        if not self.token:
            print("User not logged in, skipping list_analysis_requests")
            return

        list_query = """
            query ListRequests($first: Int) {
                listAnalysisRequests(first: $first) { # Basic query, adjust pagination/fields as needed
                    edges { node { id status prompt createdAt } }
                    pageInfo { hasNextPage endCursor }
                }
            }
        """
        variables = {"first": 10}  # Fetch recent requests
        self.client.post(
            self.graphql_endpoint,
            json={"query": list_query, "variables": variables},
            name="GraphQL: List Analysis Requests",
        )  # Don't need catch_response if we just rely on status code check by default

    @task(1)  # Lower weight: Simulate less frequent HITL interaction
    def approve_random_action(self):
        if not self.token or not self.proposed_action_ids:
            # Note: This task requires proposed_action_ids to be populated.
            # This might happen if analysis tasks generate actions, or via test setup.
            # print("User not logged in or no actions to approve, skipping approve_action")
            return

        action_id_to_approve = random.choice(self.proposed_action_ids)

        approve_mutation = """
            mutation Approve($actionId: ID!) {
                userApprovesAction(input: { actionId: $actionId }) {
                    proposedAction { id status }
                    userErrors { message field }
                }
            }
        """
        variables = {"actionId": action_id_to_approve}
        with self.client.post(
            self.graphql_endpoint,
            json={"query": approve_mutation, "variables": variables},
            catch_response=True,
            name="GraphQL: Approve Action",
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if data.get("errors") or data.get("data", {}).get(
                    "userApprovesAction", {}
                ).get("userErrors"):
                    errors = (
                        data.get("errors")
                        or data["data"]["userApprovesAction"]["userErrors"]
                    )
                    response.failure(
                        f"Error approving action {action_id_to_approve}: {errors}"
                    )
                else:
                    response.success()
                    try:
                        self.proposed_action_ids.remove(
                            action_id_to_approve
                        )  # Avoid re-approving
                    except ValueError:
                        pass  # Action might have been removed by another user/process
            else:
                response.failure(
                    f"Approve action failed with status {response.status_code}: {response.text}"
                )

    # Add more tasks to simulate different user behaviors:
    # - Submitting analysis requests
    # - Fetching results
    # - Approving/rejecting actions (HITL)

    # def login(self):
    #     """Example login logic to get auth tokens."""
    #     # response = self.client.post("/auth/login", json={"username": "testuser", "password": "password"})
    #     # if response.status_code == 200:
    #     #     self.token = response.json().get("access_token")
    #     #     self.client.headers["Authorization"] = f"Bearer {self.token}"
    #     # else:
    #     #     print("Login failed")
    #     pass
