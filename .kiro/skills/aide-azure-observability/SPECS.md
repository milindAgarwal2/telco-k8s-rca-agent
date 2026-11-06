# Skill contract

- Uses an existing Azure CLI Entra session and never handles credentials.
- Observations remain inside one configured subscription and resource group.
- Cloud access is read-only and uses the bounded Azure MCP surface.
- Outputs distinguish access, observation, inference, and service health.
- Remediation and monitoring-resource creation are out of scope.
