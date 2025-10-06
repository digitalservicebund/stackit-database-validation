import logging
import re
from unittest.mock import patch, MagicMock

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from main import app

runner = CliRunner()


def mock_httpx_responses(
    httpx_mock: HTTPXMock,
    prod_cluster_ip: list[str],
    non_prod_cluster_ip: list[str],
    prod_db_acl: list[str],
    non_prod_db_acl: list[str] | None,
):
    httpx_mock.add_response(
        url=re.compile(".*/clusters/production"),
        json={"status": {"egressAddressRanges": prod_cluster_ip}},
    )
    httpx_mock.add_response(
        url=re.compile(".*/clusters/non-prod"),
        json={"status": {"egressAddressRanges": non_prod_cluster_ip}},
    )
    httpx_mock.add_response(
        url=re.compile(".*/projects"),
        json={
            "items": [
                {"projectId": "project_id_1", "name": "project_name_1 PROD"},
                {"projectId": "project_id_2", "name": "project_name_2 NON-PROD"},
            ]
        },
    )
    httpx_mock.add_response(
        url=re.compile(".*/projects/project_id_1/regions/eu01/instances"),
        json={
            "items": [
                {"name": "p_1_db_1_name", "id": "p_1_db_1_id"},
                {"name": "p_1_db_2_name", "id": "p_1_db_2_id"},
            ]
        },
    )
    httpx_mock.add_response(
        url=re.compile(".*/projects/project_id_2/regions/eu01/instances"),
        json={
            "items": [{"name": "p_2_db_1_name", "id": "p_2_db_1_id"}]
            if non_prod_db_acl
            else []
        },
    )

    httpx_mock.add_response(
        url=re.compile(".*/instances/p_1_db_1_id"),
        json={"item": {"acl": {"items": prod_db_acl}}},
    )
    httpx_mock.add_response(
        url=re.compile(".*/instances/p_1_db_2_id"),
        json={"item": {"acl": {"items": prod_db_acl}}},
    )
    if non_prod_db_acl:
        httpx_mock.add_response(
            url=re.compile(".*/instances/p_2_db_1_id"),
            json={"item": {"acl": {"items": non_prod_db_acl}}},
        )


class TestValidateOrg:
    @patch("main.get_bearer_token")
    def test_all_acls_correct(
        self, get_bearer_token_mock: MagicMock, httpx_mock: HTTPXMock
    ):
        mock_httpx_responses(
            httpx_mock,
            prod_cluster_ip=["1.1.1.1/32"],
            non_prod_cluster_ip=["2.2.2.2/32"],
            prod_db_acl=["1.1.1.1/32"],
            non_prod_db_acl=["2.2.2.2/32"],
        )

        result = runner.invoke(app, ["validate-org", "org-id"])
        assert result.exit_code == 0

    @patch("main.get_bearer_token")
    def test_additional_ips_in_acl(
        self,
        get_bearer_token_mock: MagicMock,
        httpx_mock: HTTPXMock,
        caplog: pytest.LogCaptureFixture,
    ):
        mock_httpx_responses(
            httpx_mock,
            prod_cluster_ip=["1.1.1.1/32"],
            non_prod_cluster_ip=["2.2.2.2/32"],
            prod_db_acl=["1.1.1.1/32", "3.3.3.3/32"],
            non_prod_db_acl=["2.2.2.2/32"],
        )

        with caplog.at_level(logging.INFO):
            result = runner.invoke(app, ["validate-org", "org-id"])
        assert result.exit_code == 1
        assert (
            "Database instance p_1_db_1_name (p_1_db_1_id): ACL check failed"
            in caplog.text
        )

    @patch("main.get_bearer_token")
    def test_without_db_in_non_prod(
        self,
        get_bearer_token_mock: MagicMock,
        httpx_mock: HTTPXMock,
        caplog: pytest.LogCaptureFixture,
    ):
        mock_httpx_responses(
            httpx_mock,
            prod_cluster_ip=["1.1.1.1/32"],
            non_prod_cluster_ip=["2.2.2.2/32"],
            prod_db_acl=["1.1.1.1/32"],
            non_prod_db_acl=None,
        )

        with caplog.at_level(logging.INFO):
            result = runner.invoke(app, ["validate-org", "org-id"])
        assert result.exit_code == 0
        assert "No databases in this project" in caplog.text


def mock_httpx_responses_for_validate_projects(
    httpx_mock: HTTPXMock,
    prod_db_acl: list[str],
    non_prod_db_acl: list[str] | None,
):
    # Project details for each provided project_id
    httpx_mock.add_response(
        url=re.compile(".*/v2/projects/project_id_1$"),
        json={"name": "project_name_1 PROD"},
    )
    httpx_mock.add_response(
        url=re.compile(".*/v2/projects/project_id_2$"),
        json={"name": "project_name_2 NON-PROD"},
    )

    # Instances in each project
    httpx_mock.add_response(
        url=re.compile(".*/projects/project_id_1/regions/eu01/instances"),
        json={
            "items": [
                {"name": "p_1_db_1_name", "id": "p_1_db_1_id"},
                {"name": "p_1_db_2_name", "id": "p_1_db_2_id"},
            ]
        },
    )
    httpx_mock.add_response(
        url=re.compile(".*/projects/project_id_2/regions/eu01/instances"),
        json={
            "items": [{"name": "p_2_db_1_name", "id": "p_2_db_1_id"}]
            if non_prod_db_acl
            else []
        },
    )

    # ACLs for instances
    httpx_mock.add_response(
        url=re.compile(".*/instances/p_1_db_1_id$"),
        json={"item": {"acl": {"items": prod_db_acl}}},
    )
    httpx_mock.add_response(
        url=re.compile(".*/instances/p_1_db_2_id$"),
        json={"item": {"acl": {"items": prod_db_acl}}},
    )
    if non_prod_db_acl:
        httpx_mock.add_response(
            url=re.compile(".*/instances/p_2_db_1_id$"),
            json={"item": {"acl": {"items": non_prod_db_acl}}},
        )


class TestValidateProjects:
    @patch("main.get_bearer_token")
    def test_all_acls_correct(
        self, get_bearer_token_mock: MagicMock, httpx_mock: HTTPXMock
    ):
        mock_httpx_responses_for_validate_projects(
            httpx_mock,
            prod_db_acl=["1.1.1.1/32"],
            non_prod_db_acl=["2.2.2.2/32"],
        )

        result = runner.invoke(
            app,
            [
                "validate-projects",
                "project_id_1",
                "project_id_2",
                "--prod-egress-range",
                "1.1.1.1/32",
                "--non-prod-egress-range",
                "2.2.2.2/32",
            ],
        )
        assert result.exit_code == 0

    @patch("main.get_bearer_token")
    def test_additional_ips_in_acl(
        self,
        get_bearer_token_mock: MagicMock,
        httpx_mock: HTTPXMock,
        caplog: pytest.LogCaptureFixture,
    ):
        mock_httpx_responses_for_validate_projects(
            httpx_mock,
            prod_db_acl=["1.1.1.1/32", "3.3.3.3/32"],
            non_prod_db_acl=["2.2.2.2/32"],
        )

        with caplog.at_level(logging.INFO):
            result = runner.invoke(
                app,
                [
                    "validate-projects",
                    "project_id_1",
                    "project_id_2",
                    "--prod-egress-range",
                    "1.1.1.1/32",
                    "--non-prod-egress-range",
                    "2.2.2.2/32",
                ],
            )
        assert result.exit_code == 1
        assert (
            "Database instance p_1_db_1_name (p_1_db_1_id): ACL check failed"
            in caplog.text
        )

    @patch("main.get_bearer_token")
    def test_without_db_in_non_prod(
        self,
        get_bearer_token_mock: MagicMock,
        httpx_mock: HTTPXMock,
        caplog: pytest.LogCaptureFixture,
    ):
        mock_httpx_responses_for_validate_projects(
            httpx_mock,
            prod_db_acl=["1.1.1.1/32"],
            non_prod_db_acl=None,
        )

        with caplog.at_level(logging.INFO):
            result = runner.invoke(
                app,
                [
                    "validate-projects",
                    "project_id_1",
                    "project_id_2",
                    "--prod-egress-range",
                    "1.1.1.1/32",
                    "--non-prod-egress-range",
                    "2.2.2.2/32",
                ],
            )
        assert result.exit_code == 0
        assert "No databases in this project" in caplog.text
