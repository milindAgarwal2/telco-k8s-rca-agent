{{- define "rca-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "rca-agent.fullname" -}}
{{- printf "%s" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "rca-agent.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "rca-agent.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "rca-agent.labels" -}}
app.kubernetes.io/name: {{ include "rca-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "rca-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "rca-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
