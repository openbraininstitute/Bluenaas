import os
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

# Set minimal env vars needed for imports
os.environ.setdefault("ACCOUNTING_DISABLED", "1")

from entitysdk.types import CircuitScale
from app.services.api.circuit.simulation import run_circuit_simulation_batch


class TestCircuitSimulationBatchClosures(unittest.TestCase):
    """Test suite to ensure closure variables are captured correctly in batch simulations."""

    @patch("app.services.api.circuit.simulation.Client")
    @patch("app.services.api.circuit.simulation._fetch_sim")
    @patch("app.services.api.circuit.simulation._fetch_sim_campaign")
    @patch("app.services.api.circuit.simulation._get_sim_params_map")
    @patch("app.services.api.circuit.simulation._create_sim_exec_entity")
    @patch("app.services.api.circuit.simulation.async_accounting_session_factory")
    @patch("app.services.api.circuit.simulation.dispatch")
    @patch("app.services.api.circuit.simulation.interleave_async_iterators")
    @patch("app.services.api.circuit.simulation.x_ndjson_http_stream")
    @patch("app.services.api.circuit.simulation.run_async")
    def test_callbacks_capture_correct_session_and_execution_id(
        self,
        mock_run_async,
        mock_http_stream,
        mock_interleave,
        mock_dispatch,
        mock_accounting_factory,
        mock_create_exec,
        mock_get_params,
        mock_fetch_campaign,
        mock_fetch_sim,
        mock_client_class,
    ):
        """Test that on_start, on_success, on_failure callbacks capture correct variables per simulation."""

        async def test():
            # Setup test data
            sim_ids = [uuid4(), uuid4(), uuid4()]
            campaign_id = uuid4()

            # Mock simulations and track circuit IDs
            mock_sims = {}
            circuit_ids = {}
            for sim_id in sim_ids:
                mock_sim = Mock()
                mock_sim.id = sim_id
                mock_sim.simulation_campaign_id = campaign_id
                circuit_id = uuid4()
                mock_sim.entity_id = circuit_id
                circuit_ids[sim_id] = circuit_id
                mock_sim.name = f"sim-{sim_id}"
                mock_sims[sim_id] = mock_sim

            async def fetch_sim_side_effect(sid, client):
                return mock_sims[sid]

            mock_fetch_sim.side_effect = fetch_sim_side_effect

            # Mock campaign
            mock_campaign = Mock()
            mock_campaign.name = "test-campaign"

            async def fetch_campaign_side_effect(cid, client):
                return mock_campaign

            mock_fetch_campaign.side_effect = fetch_campaign_side_effect

            # Mock simulation params
            mock_params = {}
            for sim_id in sim_ids:
                param = Mock()
                param.num_cells = 100
                param.tstop = 1000
                mock_params[sim_id] = param

            async def get_params_side_effect(*args, **kwargs):
                return mock_params

            mock_get_params.side_effect = get_params_side_effect

            # Mock accounting sessions - track which session is used
            mock_sessions = {}
            for sim_id in sim_ids:
                session = AsyncMock()
                session.sim_id = sim_id  # Tag for verification
                mock_sessions[sim_id] = session

            def oneshot_session_side_effect(**kwargs):
                # Extract sim name to determine which session to return
                name = kwargs.get("name", "")
                for sim_id in sim_ids:
                    if str(sim_id) in name:
                        return mock_sessions[sim_id]
                return mock_sessions[sim_ids[0]]

            mock_accounting_factory.oneshot_session.side_effect = oneshot_session_side_effect

            # Mock circuits
            mock_circuits = {}
            for sim_id in sim_ids:
                circuit = Mock()
                circuit.scale = CircuitScale.small
                mock_circuits[circuit_ids[sim_id]] = circuit

            # Mock client.get_entity to return circuits
            def get_entity_side_effect(entity_id, entity_type):
                from entitysdk.models import Circuit, Simulation
                from entitysdk.client import Entity
                from app.core.circuit.circuit import CircuitOrigin
                
                if entity_type == Circuit and entity_id in mock_circuits:
                    return mock_circuits[entity_id]
                if entity_type == Simulation and entity_id in mock_sims:
                    return mock_sims[entity_id]
                if entity_type == Entity and entity_id in circuit_ids.values():
                    # Return entity with type set to CIRCUIT
                    entity = Mock()
                    entity.type = CircuitOrigin.CIRCUIT.value
                    return entity
                return Mock()

            mock_client_class.return_value.get_entity.side_effect = get_entity_side_effect

            # Mock run_async to execute the lambda
            async def run_async_side_effect(func):
                return func()

            mock_run_async.side_effect = run_async_side_effect

            # Mock execution entities
            mock_exec_entities = {}
            for sim_id in sim_ids:
                exec_entity = Mock()
                exec_entity.id = uuid4()
                mock_exec_entities[sim_id] = exec_entity

            exec_call_count = [0]

            async def create_exec_side_effect(sim, client):
                exec_entity = mock_exec_entities[sim.id]
                exec_call_count[0] += 1
                return exec_entity

            mock_create_exec.side_effect = create_exec_side_effect

            # Capture callbacks from dispatch calls
            captured_callbacks = []

            async def dispatch_side_effect(*args, **kwargs):
                callbacks = {
                    "on_start": kwargs.get("on_start"),
                    "on_success": kwargs.get("on_success"),
                    "on_failure": kwargs.get("on_failure"),
                    "job_id": kwargs.get("job_id"),
                }
                captured_callbacks.append(callbacks)
                mock_stream = AsyncMock()
                return (Mock(), mock_stream)

            mock_dispatch.side_effect = dispatch_side_effect

            # Mock other dependencies
            mock_request = Mock()
            mock_queue = Mock()
            mock_project_context = Mock()
            mock_project_context.project_id = "test-project"
            mock_auth = Mock()
            mock_auth.access_token = "test-token"
            mock_auth.decoded_token = Mock()
            mock_auth.decoded_token.sub = "test-user"

            mock_interleave.return_value = AsyncMock()
            mock_http_stream.return_value = AsyncMock()

            # Execute the function
            await run_circuit_simulation_batch(
                sim_ids,
                request=mock_request,
                job_queue=mock_queue,
                project_context=mock_project_context,
                auth=mock_auth,
            )

            # Verify we have callbacks for all simulations
            self.assertEqual(len(captured_callbacks), 3)

            # Test that each callback uses the correct session and execution_id
            for i, callbacks in enumerate(captured_callbacks):
                job_id = UUID(callbacks["job_id"])

                # Find which simulation this job belongs to
                sim_id = None
                for sid, exec_entity in mock_exec_entities.items():
                    if exec_entity.id == job_id:
                        sim_id = sid
                        break

                self.assertIsNotNone(sim_id, f"Could not find sim_id for job {job_id}")

                # Execute on_start and verify correct session is used
                await callbacks["on_start"]()
                expected_session = mock_sessions[sim_id]
                expected_session.start.assert_called_once()

                # Execute on_success and verify correct session is used
                await callbacks["on_success"]()
                expected_session.finish.assert_called_once()

                # Reset for on_failure test
                expected_session.finish.reset_mock()

                # Execute on_failure and verify correct session and execution_id
                await callbacks["on_failure"](None)
                expected_session.finish.assert_called_once()

            # Verify all sessions were used (no session was reused for all callbacks)
            for session in mock_sessions.values():
                self.assertGreater(session.start.call_count, 0, "Session should have been started")
                self.assertGreater(
                    session.finish.call_count, 0, "Session should have been finished"
                )

        asyncio.run(test())


if __name__ == "__main__":
    unittest.main()
