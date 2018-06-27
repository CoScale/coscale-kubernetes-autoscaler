# CoScale Kubernetes Autoscaler

The **CoScale Autoscaler** retrieves **metric data** from the CoScale platform, checks whether the metric data is within the provided bounds and **scales a Kubernetes Deployment** accordingly.

## Configuration

The autoscaler reads the configuration (in JSON format) from the **SCALER_CONFIG** environment variable. For example:

```
[
  {
    "namespace_name": "production",
    "deployment_name": "apache",
    "metric": {
      "name": "Docker container cpu usage percent from limit",
      "low_value": 20,
      "high_value": 80,
      "avg_interval_sec": 300
    },
    "scale_backoff_sec": 600,
    "min_replicas": 3,
    "max_replicas": 10
  }
]
```

This configuration checks the *Docker container cpu usage percent from limit* metric for the *apache* deployment in the *production* namespace. The **average metric value for all containers in the deployment** is calculated over a period of *300* seconds. If the average value is lower than *20*, the number of replicas in the deployment is decreased by 1, but not below the minimum number of replicas *3*. If the average value is higher than *80*, the number of replicas in the deployment is increased by 1, but not above the maximum number of replicas *10*. The metric values are checked every minute, scaling will only take place if *600* seconds have elapsed since the last scaling.

To connect to the CoScale platform the following environment variables are used

* *API_URL*: The base url for the CoScale Platform (eg. https://api.coscale.com)
* *APP_ID*: The application UUID
* *ACCESS_TOKEN*: A valid access token (UUID) for the provided APP_ID

Both the *APP_ID* and *ACCESS_TOKEN* can be found on the "Users & Teams > Access Tokens" page in the CoScale UI.

## Deployment

The CoScale Autoscaler should be deployed on the Kubernetes cluster that you want to autoscale. The container needs a ServiceAccount and ClusterRoleBinding to communicate with the Kubernetes API.

```
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: coscale-autoscaler
  namespace: coscale
---
apiVersion: rbac.authorization.k8s.io/v1beta1
kind: ClusterRoleBinding
metadata:
  annotations:
    rbac.authorization.kubernetes.io/autoupdate: "true"
  labels:
    kubernetes.io/bootstrapping: rbac-defaults
  name: coscale-autoscaler
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- kind: ServiceAccount
  name: coscale-autoscaler
  namespace: coscale
---
apiVersion: extensions/v1beta1
kind: ReplicaSet
metadata:
  labels:
    name: coscale-autoscaler
  name: coscale-autoscaler
  namespace: coscale
spec:
  replicas: 1
  template:
    metadata:
      labels:
        name: coscale-autoscaler
    spec:
      serviceAccountName: coscale-autoscaler
      containers:
      - image: coscale/coscale-kubernetes-autoscaler:1.1.0
        name: autoscaler
        env:
        - name: API_URL
          value: "https://api.coscale.com"
        - name: APP_ID
          value: "00000000-0000-0000-0000-000000000000"
        - name: ACCESS_TOKEN
          value: "00000000-0000-0000-0000-000000000000"
        - name: SCALER_CONFIG
          value: '[{"namespace_name":"production","deployment_name":"apache","metric":{"name":"Docker container cpu usage percent from limit","low_value":20,"high_value":80,"avg_interval_sec":300},"scale_backoff_sec":600,"min_replicas":3,"max_replicas":10}]'
EOF
```

**Don't forget to update API_URL, APP_ID and ACCESS_TOKEN in the example above.**


## OpenShift Deployment Configs

The CoScale Autoscaler has support for both Kubernetes Deployments and OpenShift Deployment configs (https://docs.openshift.com/enterprise/3.0/dev_guide/deployments.html).

Add the **deployment_type** field with value **Deployment configs** to the configuration to use the Autoscaler with OpenShift Deployment configs:

```
[
  {
    "namespace_name": "production",
    "deployment_type": "Deployment configs",
    "deployment_name": "apache",
    "metric": {
      "name": "Docker container cpu usage percent from limit",
      "low_value": 20,
      "high_value": 80,
      "avg_interval_sec": 300
    },
    "scale_backoff_sec": 600,
    "min_replicas": 3,
    "max_replicas": 10
  }
]
```

Deploying the CoScale autoscaler on OpenShift can be done using the following commands:

```
oc project coscale
oc create serviceaccount coscale
oadm policy add-cluster-role-to-user cluster-admin system:serviceaccount:coscale:coscale

cat << EOF | oc apply -f -
apiVersion: extensions/v1beta1
kind: ReplicaSet
metadata:
  labels:
    name: coscale-autoscaler
  name: coscale-autoscaler
  namespace: coscale
spec:
  replicas: 1
  template:
    metadata:
      labels:
        name: coscale-autoscaler
    spec:
      serviceAccountName: coscale-autoscaler
      containers:
      - image: coscale/coscale-kubernetes-autoscaler:1.1.0
        name: autoscaler
        env:
        - name: API_URL
          value: "https://api.coscale.com"
        - name: APP_ID
          value: "00000000-0000-0000-0000-000000000000"
        - name: ACCESS_TOKEN
          value: "00000000-0000-0000-0000-000000000000"
        - name: SCALER_CONFIG
          value: '[{"namespace_name":"production","deployment_type":"Deployment configs","deployment_name":"apache","metric":{"name":"Docker container cpu usage percent from limit","low_value":20,"high_value":80,"avg_interval_sec":300},"scale_backoff_sec":600,"min_replicas":3,"max_replicas":10}]'
EOF
```
