# STACKIT Database ACL Validation

A GitHub Action to validate the ACL configuration of all postgres databases in a STACKIT Organisation or Project. This
makes sure that the databases are only accessible via the cluster.

## Usage

### Validate all DBs in an organisation

The action will fail as soon as at least one database has other ACLs than the cluster egress CIDR range. The output will
contain more details about what project and what database is causing the problem.

```yaml
jobs:
  db-validation:
    name: "STACKIT DB ACL Validation"
    runs-on: ubuntu-latest
    steps:
      - name: "Run validation"
        uses: digitalservicebund/stackit-database-validation@main
        with:
          organisation_id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
          stackit_service_account_key: ${{ secrets.STACKIT_SERVICE_ACCOUNT_KEY }}
```

### Validate all DBs in a project

```yaml
jobs:
  db-validation:
    name: "STACKIT DB ACL Validation"
    runs-on: ubuntu-latest
    steps:
      - name: "Run validation"
        uses: digitalservicebund/stackit-database-validation@main
        with:
          project_id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
          prod_egress_range: 10.0.0.0/32  # get this from the platfrom team
          non_prod_egress_range: 10.0.0.1/32  # get this from the platfrom team
          stackit_service_account_key: ${{ secrets.STACKIT_SERVICE_ACCOUNT_KEY }}
```
