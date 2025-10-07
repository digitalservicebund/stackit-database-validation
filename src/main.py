import logging
import subprocess
from functools import lru_cache

import httpx
import typer
from pydantic import BaseModel
from pydantic_settings import BaseSettings

logging.basicConfig(
    level="INFO",
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# Hide httpx info logs
logging.getLogger("httpx").setLevel("WARNING")
logger = logging.getLogger(__name__)

app = typer.Typer(pretty_exceptions_short=False)


class ClusterConfig(BaseModel):
    name: str
    project_id: str
    egress_range: list[str] | None

    def get_egress_range(self, settings: "OrgSettings"):
        self.egress_range = get_cluster_egress_ip(self.project_id, self.name, settings)


class StackITSettings(BaseSettings):
    stackit_service_account_key_path: str = "../stackit-credentials.json"


class OrgSettings(StackITSettings):
    prod_cluster: ClusterConfig = ClusterConfig(
        name="production",
        project_id="df003e90-b77d-4d31-a06c-cd7f4013076d",
        egress_range=None,
    )
    non_prod_cluster: ClusterConfig = ClusterConfig(
        name="non-prod",
        project_id="dceaea5e-fc88-4adb-8c7f-6bcb112835bb",
        egress_range=None,
    )
    stackit_service_account_key_path: str = "../stackit-credentials.json"


@lru_cache
def get_bearer_token(stackit_service_account_key_path: str):
    result = subprocess.run(
        [
            "stackit",
            "auth",
            "activate-service-account",
            "--service-account-key-path",
            stackit_service_account_key_path,
            "--only-print-access-token",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    token = result.stdout.strip()
    return token


def get_cluster_egress_ip(
    project_id: str, cluster_name: str, config: OrgSettings
) -> list[str]:
    """Fetches the egress IP of a specific cluster."""
    url = f"https://ske.api.stackit.cloud/v2/projects/{project_id}/regions/eu01/clusters/{cluster_name}"
    response = httpx.get(
        url,
        headers={
            "Authorization": f"Bearer {get_bearer_token(config.stackit_service_account_key_path)}",
            "Accept": "application/json",
        },
    )
    logger.debug(f"Cluster response: {response.text}")
    response.raise_for_status()
    cluster_data = response.json()
    egress_ip = cluster_data["status"]["egressAddressRanges"]
    if not egress_ip:
        raise ValueError("Egress IP not found in cluster details.")
    return egress_ip


def get_all_projects(
    organization_id: str, config: OrgSettings
) -> list[tuple[str, str]]:
    """Fetches all projects from the Resource Manager API."""
    url = "https://resource-manager.api.stackit.cloud/v2/projects"
    response = httpx.get(
        url,
        headers={
            "Authorization": f"Bearer {get_bearer_token(config.stackit_service_account_key_path)}",
            "Accept": "application/json",
        },
        params={"containerParentId": organization_id},
    )
    logger.debug(f"Projects response: {response.text}")
    response.raise_for_status()
    projects = response.json()["items"]
    # Return both the project ID and its name for validation logic
    return [(p.get("projectId"), p.get("name")) for p in projects]


def get_project_details(
    project_ids: list[str], config: StackITSettings
) -> list[tuple[str, str]]:
    """Fetches project details for a list of project ids from the Resource Manager API."""
    projects = []
    for project_id in project_ids:
        url = f"https://resource-manager.api.stackit.cloud/v2/projects/{project_id}"
        response = httpx.get(
            url,
            headers={
                "Authorization": f"Bearer {get_bearer_token(config.stackit_service_account_key_path)}",
                "Accept": "application/json",
            },
        )
        logger.debug(f"Projects response: {response.text}")
        response.raise_for_status()
        projects.append((project_id, response.json()["name"]))
    return projects


def get_databases_in_project(project_id, config: StackITSettings):
    """Fetches all PostgreSQL Flexible databases for a given project."""
    url = f"https://postgres-flex-service.api.stackit.cloud/v2/projects/{project_id}/regions/eu01/instances"
    response = httpx.get(
        url,
        headers={
            "Authorization": f"Bearer {get_bearer_token(config.stackit_service_account_key_path)}",
            "Accept": "application/json",
        },
    )
    logger.debug(f"Databases response: {response.text}")
    response.raise_for_status()
    return response.json().get("items", [])


def get_acls(project_id: str, instance_id: str, config: StackITSettings):
    """Fetches all ACLs of a PostgreSQL database."""
    url = f"https://postgres-flex-service.api.stackit.cloud/v2/projects/{project_id}/regions/eu01/instances/{instance_id}"
    response = httpx.get(
        url,
        headers={
            "Authorization": f"Bearer {get_bearer_token(config.stackit_service_account_key_path)}",
            "Accept": "application/json",
        },
    )
    logger.debug(f"ACL response: {response.text}")
    response.raise_for_status()
    instance_details = response.json()
    acl_rules = instance_details["item"]["acl"].get("items", [])
    return acl_rules


def check_database_acl_of_project(
    project_id: str,
    cluster_egress_range: list[str],
    settings: StackITSettings,
) -> bool:
    all_acls_are_correct = True
    # Determine the correct egress IP based on the project name
    databases = get_databases_in_project(project_id, settings)
    if not databases:
        logger.info("No databases in this project")
    for db in databases:
        db_instance_id = db["id"]
        db_name = db["name"]
        acl_rules = get_acls(project_id, db_instance_id, settings)
        if set(acl_rules) == set(cluster_egress_range):
            logger.info(
                f"✅ Database instance {db_name} ({db_instance_id}): ACL is correct."
            )
        else:
            logger.error(
                f"❌ Database instance {db_name} ({db_instance_id}): ACL check failed.\n"
                f"Expected: {cluster_egress_range}\n"
                f"Found:    {acl_rules}"
            )
            all_acls_are_correct = False
    return all_acls_are_correct


def get_egress_range(
    project_name: str,
    prod_cluster_egress_range: list[str],
    non_prod_cluster_egress_range: list[str],
) -> list[str]:
    if "NON-PROD" in project_name.upper():
        cluster_egress_range = non_prod_cluster_egress_range
        logger.info(f"Checking project: {project_name} - Using NON-PROD cluster IP")
    else:
        cluster_egress_range = prod_cluster_egress_range
        logger.info(f"Checking project: {project_name} - Using PROD cluster IP")
    return cluster_egress_range


@app.command()
def validate_org(organization_id: str):
    logger.info("Starting Stackit ACL check script...")

    settings = OrgSettings()

    logger.info("Getting cluster egress IPs...")
    settings.prod_cluster.get_egress_range(settings)
    settings.non_prod_cluster.get_egress_range(settings)

    logger.info(f"PROD Cluster Egress IP: {settings.prod_cluster.egress_range}")
    logger.info(f"NON-PROD Cluster Egress IP: {settings.non_prod_cluster.egress_range}")

    logger.info("Getting all projects...")
    projects = get_all_projects(organization_id, settings)
    if not projects:
        logger.info("No projects found. Exiting.")
        return
    logger.info(f"Found {len(projects)} projects.")

    logger.info("Checking database ACLs across all projects...")

    all_acls_are_correct = True
    for project_id, project_name in projects:
        cluster_egress_range = get_egress_range(
            project_name,
            settings.prod_cluster.egress_range,
            settings.non_prod_cluster.egress_range,
        )

        if not check_database_acl_of_project(
            project_id, cluster_egress_range, settings
        ):
            all_acls_are_correct = False

    if all_acls_are_correct:
        logger.info("All database ACLs are correctly configured. 🎉")
    else:
        raise Exception(
            "Some database ACLs do not match the expected cluster egress IP. 😞"
        )


@app.command()
def validate_projects(
    project_ids: list[str],
    prod_egress_range: list[str] | None = typer.Option(
        help="Egress IP Range of the Production Cluster. Env: PROD_EGRESS_RANGE",
        default=None,
    ),
    non_prod_egress_range: list[str] | None = typer.Option(
        help="Egress IP Range of the Non-Prod Cluster. Env: NON_PROD_EGRESS_RANGE",
        default=None,
    ),
):
    logger.info("Starting Stackit ACL check script...")
    settings = StackITSettings()
    all_acls_are_correct = True
    projects = get_project_details(project_ids, settings)
    for project_id, project_name in projects:
        cluster_egress_range = get_egress_range(
            project_name, prod_egress_range, non_prod_egress_range
        )
        if not check_database_acl_of_project(
            project_id, cluster_egress_range, settings
        ):
            all_acls_are_correct = False

    if all_acls_are_correct:
        logger.info("All database ACLs are correctly configured. 🎉")
    else:
        raise Exception(
            "Some database ACLs do not match the expected cluster egress IP. 😞"
        )


if __name__ == "__main__":
    app()
