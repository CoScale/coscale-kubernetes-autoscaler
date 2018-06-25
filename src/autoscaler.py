'''The CoScale Autoscaler retrieves metric data from the CoScale platform,
checks whether the metric data is within the provided bounds
and scales a Kubernetes Deployment accordingly.'''

import subprocess
import os
import sys
import sched
import json
import time
import logging

import kubernetes

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                    level=logging.INFO, stream=sys.stdout)

class CliWrapper:
    '''A CliWrapper provides access to the CoScale API by wrapping the CoScale CLI.'''

    def __init__(self, cli_path, api_url, app_id, access_token):
        self.cli_path = cli_path
        self.api_url = api_url
        self.app_id = app_id
        self.access_token = access_token
        self.__set_config()

    def __set_config(self):
        subprocess.check_output([self.cli_path, 'config', 'set', '--api-url', self.api_url,
                                 '--app-id', self.app_id, '--access-token', self.access_token])

    def __execute(self, args, parse_json=True):
        output = subprocess.check_output([self.cli_path] + args)
        return json.loads(output) if parse_json else output

    def get_metric_by_name(self, metric_name):
        '''Get a metric by it's name.'''
        resp = self.__execute(['metric', 'get', '--name', metric_name])
        return None if len(resp) == 0 else resp[0]

    def get_server_group(self, server_group_path):
        '''Get a server group by it's path.'''
        resp = self.__execute(['servergroup', 'get', '--path', server_group_path])
        return None if len(resp) == 0 else resp[0]

    def get_metric_data(self, metric_id, server_group_id, start, stop):
        '''Get average metric data for a given metric, server group and start, stop bounds.'''
        return self.__execute(['data', 'get', '--id', '%d' % metric_id,
                               '--subjectIds', 'g%d' % server_group_id,
                               '--start', '%d' % start, '--stop', '%d' % stop])


class Scaler:
    '''A Scaler retrieves the CoScale metrics using CLI and updates the replicas in Kubernetes.'''

    def __init__(self, config, cli, kubernetes_appsv1api):
        self.cli = cli

        self.namespace_name = config['namespace_name']
        self.deployment_name = config['deployment_name']
        self.deployment_type = config.get('deployment_type', 'Deployments')
        self.metric_name = config['metric']['name']
        self.low_value = float(config['metric']['low_value'])
        self.high_value = float(config['metric']['high_value'])
        self.avg_interval = int(config['metric']['avg_interval_sec'])
        self.backoff = int(config['scale_backoff_sec'])
        self.min_replicas = int(config['min_replicas'])
        self.max_replicas = int(config['max_replicas'])

        self.metric = cli.get_metric_by_name(self.metric_name)
        if self.metric is None:
            raise Exception("Could not find metric '%s'" % self.metric_name)

        group_path = 'Kubernetes/Namespaces/%s/%s/%s' % \
                     (self.namespace_name, self.deployment_type, self.deployment_name)
        self.server_group = cli.get_server_group(group_path)
        if self.server_group is None:
            raise Exception("Could not find server group '%s'" % group_path)

        self.kubernetes_appsv1api = kubernetes_appsv1api
        self.last_scaling = 0

        logging.info('Scaler %s is using metric id %d and server group id %s',
                     self, self.metric['id'], self.server_group['id'])

    def run(self):
        '''Runs one iteration of the scaler.'''
        if time.time() > self.last_scaling + self.backoff:
            current_value = self.metric_value()
            logging.info('Checking %s : %f %s', self, current_value, self.metric['unit'])

            if current_value is None:
                logging.error('Failed to retrieve metric data %s', self)
            else:
                if current_value < self.low_value:
                    replicas = self.current_replicas()
                    if replicas > self.min_replicas:
                        self.scale(replicas - 1)
                    else:
                        logging.info('Scaler %s reached min replicas of %d',
                                     self, self.min_replicas)
                elif current_value > self.high_value:
                    replicas = self.current_replicas()
                    if replicas < self.max_replicas:
                        self.scale(replicas + 1)
                    else:
                        logging.info('Scaler %s reached max replicas of %d',
                                     self, self.max_replicas)
        else:
            logging.info('Scaler %s is in backoff after last scaling', self)

    def metric_value(self):
        '''Retrieve the metric value using the CoScale CLI.'''
        metric_data = self.cli.get_metric_data(self.metric['id'], self.server_group['id'],
                                               -self.avg_interval - 60, 0)
        if len(metric_data) != 1:
            return None

        pairs = metric_data[0]['values']
        if len(pairs) == 0:
            return None

        return sum([value for (timestamp, value) in pairs]) / len(pairs)

    def current_replicas(self):
        '''Get the current number of replicas from the Kubernetes API.'''
        resp = self.kubernetes_appsv1api.read_namespaced_deployment_scale(self.deployment_name,
                                                                          self.namespace_name)
        return resp.status.replicas

    def scale(self, replicas):
        '''Scale the Kubernetes deployment to the given number of replicas.'''
        logging.info('Scaling %s to %d replicas', self, replicas)

        body = kubernetes.client.V1Scale()
        body.metadata = kubernetes.client.V1ObjectMeta()
        body.metadata.namespace = self.namespace_name
        body.metadata.name = self.deployment_name
        body.spec = kubernetes.client.V1ScaleSpec()
        body.spec.replicas = replicas
        self.kubernetes_appsv1api.replace_namespaced_deployment_scale(self.deployment_name,
                                                                      self.namespace_name, body)
        self.last_scaling = time.time()

    def __str__(self):
        return '"%s" on "%s:%s"' % (self.metric_name, self.namespace_name, self.deployment_name)


def run_and_schedule(scaler, scheduler, interval):
    '''Run the scaler and schedule it on the scheduler after the provided interval (in seconds).'''
    try:
        scaler.run()
    except Exception:
        logging.exception('Exception while running scaler on %s', scaler)
    finally:
        scheduler.enter(interval, 1, run_and_schedule, argument=(scaler, scheduler, interval))


def run_scalers(cli_path, api_url, app_id, access_token, config, interval):
    '''Run the scalers in the config dict.'''
    cli = CliWrapper(cli_path, api_url, app_id, access_token)
    kubernetes_api = kubernetes.client.AppsV1Api()

    scheduler = sched.scheduler()

    for item in config:
        try:
            scaler = Scaler(item, cli, kubernetes_api)
            logging.info('Starting scaler %s', scaler)
            run_and_schedule(scaler, scheduler, interval)
        except Exception as e:
            logging.exception('Failed to initialise scaler with configuration %s: %s', item, e)

    scheduler.run()


def main():
    '''Get the configuration from the environment variables and start the scalers.'''
    cli_path = os.environ.get('CLI_PATH', '/opt/coscale/autoscaler/coscale-cli')

    api_url = os.environ.get('API_URL', 'https://api.coscale.com')
    app_id = os.environ.get('APP_ID')
    access_token = os.environ.get('ACCESS_TOKEN')
    json_config = os.environ.get('SCALER_CONFIG')
    interval = int(os.environ.get('CHECK_INTERVAL', '60'))

    if app_id is None or access_token is None or json_config is None:
        logging.error('Please set the following environment variables: '
                      'APP_ID, ACCESS_TOKEN and SCALER_CONFIG')
        sys.exit(1)

    try:
        config = json.loads(json_config)
    except json.decoder.JSONDecodeError:
        logging.error('SCALER_CONFIG is not a valid JSON')
        sys.exit(1)
    else:
        logging.info('Connecting to Application %s on %s', app_id, api_url)
        logging.info('Configuration: %s', json.dumps(config, indent=4))

        try:
            kubernetes.config.load_incluster_config()
        except kubernetes.config.config_exception.ConfigException as config_exception:
            logging.error('Creating Kubernetes configuration failed: %s', config_exception)
            logging.error('Is the container running in a Kubernetes cluster ?')
            sys.exit(1)

        run_scalers(cli_path, api_url, app_id, access_token, config, interval)


if __name__ == '__main__':
    main()