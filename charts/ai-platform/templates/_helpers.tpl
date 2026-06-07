{{- define "ai-platform.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ai-platform.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if .Values.fullnameOverride -}}
{{- $name = .Values.fullnameOverride -}}
{{- end -}}
{{- if and .Values.fullnameOverride .Chart.Name -}}
{{- $name = printf "%s-%s" .Chart.Name .Values.fullnameOverride -}}
{{- end -}}
{{- $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ai-platform.labels" -}}
app.kubernetes.io/name: {{ include "ai-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
project: ai-selfhealing
environment: dev
{{- end -}}
