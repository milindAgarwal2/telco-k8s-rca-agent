# Azure change-control skill specification

The skill separates repository IaC authoring from cloud execution. It uses the
read-only validate/What-If tools before the single mutating apply tool, binds
approval to an exact plan ID, prohibits input drift, and treats an interrupted
or failed apply as an uncertain outcome until status is inspected. It never
grants authority beyond the local policy, Kiro hooks, or Azure controls.
