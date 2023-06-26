import base64
import time
from kubernetes import client, config
from pick import pick
import configparser
from pprint import pprint
import argparse
from kubernetes.stream import stream


class multiDCRedisCluster:
    def __init__(self, app_config, skip_err) -> None:
        # skip err for hard
        if skip_err:
            try:
                self.source_client = self.load_k8s_client(
                    app_config["source.context"]["name"])
                self.target_shake = self.load_shake_object(
                    self.source_client, app_config["target.shake"]["name"], app_config["target.shake"]["namespace"])
            except e:
                print(e)
            try:
                self.target_client = self.load_k8s_client(
                    app_config["target.context"]["name"])
                self.source_shake = self.load_shake_object(
                    self.target_client, app_config["source.shake"]["name"], app_config["source.shake"]["namespace"])
            except e:
                print(e)
            return

        self.source_client = self.load_k8s_client(
            app_config["source.context"]["name"])
        self.target_client = self.load_k8s_client(
            app_config["target.context"]["name"])
        self.source_redis = self.load_redis_object(
            self.source_client, app_config["source.redis"]["name"], app_config["source.redis"]["namespace"])

        self.target_redis = self.load_redis_object(
            self.target_client, app_config["target.redis"]["name"], app_config["target.redis"]["namespace"])
        self.config = app_config

        self.source_shake = self.load_shake_object(
            self.target_client, app_config["source.shake"]["name"], app_config["source.shake"]["namespace"])
        self.target_shake = self.load_shake_object(
            self.source_client, app_config["target.shake"]["name"], app_config["target.shake"]["namespace"])
        self.source_role = ""
        self.target_role = ""

        self.source_shake_deploy = self.load_deployment_object(
            self.target_client, app_config["source.shake"]["name"]+"-shake", app_config["source.shake"]["namespace"])
        self.target_shake_deploy = self.load_deployment_object(
            self.source_client, app_config["target.shake"]["name"]+"-shake", app_config["target.shake"]["namespace"])

        self._init_status()
        self._init_password()

    def _init_status(self):
        self.flag_source = ""
        self.source_shake_name = self.source_shake["metadata"]["name"]
        self.flag_target = ""
        self.target_shake_name = self.target_shake["metadata"]["name"]
        self.source_role = "Master"
        self.target_role = "Slave"
        if self.source_shake_deploy.status.ready_replicas == 1:
            self.source_role = "master"
            self.target_role = "slave"
            self.flag_source = "->>> syncing >>--"

        if self.target_shake_deploy.status.ready_replicas == 1:
            self.flag_target = "-<<< syncing <<-"
            self.source_role = "slave"
            self.target_role = "master"

    def display(self):
        self._init_status()
        from rich.console import Console
        from rich.table import Table
        table = Table(title="Redis Multi Data Center Status", show_lines=True)
        table.add_column("Source", justify="right",
                         style="green", no_wrap=True)
        table.add_column("Source Role", justify="right",
                         style="green", no_wrap=True)
        table.add_column("Shake", style="magenta")
        table.add_column("Shake Status", style="magenta")
        table.add_column("Target", justify="right", style="green")
        table.add_column("Target Role", justify="right",
                         style="green", no_wrap=True)

        table.add_row(self.config["source.redis"]["name"]+"("+self.source_redis["status"]["phase"]+")", self.source_role,
                      ">"+self.source_shake_name, self.flag_source, self.config["target.redis"]["name"]+"("+self.target_redis["status"]["phase"]+")", self.target_role)
        table.add_row(self.config["source.redis"]["name"]+"("+self.source_redis["status"]["phase"]+")", self.source_role,
                      "<"+self.target_shake_name, self.flag_target, self.config["target.redis"]["name"]+"("+self.target_redis["status"]["phase"]+")", self.target_role)

        console = Console()
        console.print(table)

    def failover(self):
        if self.flag_source != "":
            self.turn_off_source_shake()
            self.turn_off_target_shake()

    def try_failover(self):
        try:
            self.turn_off_source_shake()
        except e:
            print(e)
        try:
            self.turn_off_target_shake()
        except e:
            print(e)

    def load_k8s_client(self,  context_name):
        return config.new_client_from_config(context=context_name)

    def load_redis_object(self, api_client, redis_name, redis_namespace):
        api = client.CustomObjectsApi(api_client=api_client)
        resource = api.get_namespaced_custom_object(
            group="middleware.alauda.io",
            version="v1",
            name=redis_name,
            namespace=redis_namespace,
            plural="redis",
        )
        return resource

    def turn_off_source_shake(self):
        self.update_shake_replicas(self.target_client, self.source_shake, 0)

    def turn_on_source_shake(self):
        self.update_shake_replicas(self.target_client, self.source_shake, 1)

    def turn_off_target_shake(self):
        self.update_shake_replicas(self.source_client, self.target_shake, 0)

    def turn_on_target_shake(self):
        self.update_shake_replicas(self.source_client, self.target_shake, 1)

    def _init_password(self):
        source_api = client.CoreV1Api(api_client=self.source_client)
        source_secret = source_api.read_namespaced_secret(
            namespace=self.config["source.redis"]["namespace"], name=self.source_redis["status"]["passwordSecretName"])
        self.password = base64.b64decode(
            source_secret.data["password"]).decode('utf-8')

    def _init_target_password(self):
        target_api = client.CoreV1Api(api_client=self.target_client)
        target_secret = target_api.read_namespaced_secret(
            namespace=self.config["target.redis"]["namespace"], name=self.source_redis["status"]["passwordSecretName"])
        self.password = base64.b64decode(
            target_secret.data["password"]).decode('utf-8')

    def flush_all_redis(self, api_client, redis):
        if redis["spec"]["arch"] == "cluster":
            exec_command = [
                '/bin/sh',
                '-c',
                'redis-cli -a \'' + self.password + '\' --cluster call 127.0.0.1:6379 flushall'
            ]

            self.pod_exec(api_client=api_client,
                          namespace=redis["metadata"]["namespace"], name="drc-"+redis["metadata"]["name"]+"-0-0", cmd=exec_command)
        if redis["spec"]["arch"]=="sentinel":
            exec_command = [
                '/bin/sh',
                '-c',
                'redis-cli -a \'' + self.password + '\' -h' +' rfr-'+ redis["metadata"]["name"] + '-read-write -p 6379 flushall' 
            ]

            self.pod_exec(api_client=api_client,
                          namespace=redis["metadata"]["namespace"], name="rfr-"+redis["metadata"]["name"]+"-0", cmd=exec_command)

    def flush_target_redis(self):
        self.flush_all_redis(self.target_client, self.target_redis)

    def flush_source_redis(self):
        self.flush_all_redis(self.source_client, self.source_redis)

    def pod_exec(self, api_client, namespace, name, cmd):
        _client = client.CoreV1Api(api_client=api_client)

        resp = stream(_client.connect_get_namespaced_pod_exec,
                      name,
                      namespace,
                      container="redis",
                      command=cmd,
                      stderr=True, stdin=False,
                      stdout=True, tty=False)
        print("Response: " + resp)

    def update_shake_replicas(self, api_client, shake, replicas):
        print("update shake:", shake["metadata"]["name"], "replicas", replicas)
        api = client.CustomObjectsApi(api_client=api_client)
        shake["spec"]["replicas"] = replicas
        api.patch_namespaced_custom_object(
            group="middle.alauda.cn",
            version="v1alpha1",
            name=shake["metadata"]["name"],
            namespace=shake["metadata"]["namespace"],
            plural="redisshakes",
            body={"spec": shake["spec"]},
        )

    def load_shake_object(self, api_client, shake_name, shake_namespace):
        api = client.CustomObjectsApi(api_client=api_client)
        resource = api.get_namespaced_custom_object(
            group="middle.alauda.cn",
            version="v1alpha1",
            name=shake_name,
            namespace=shake_namespace,
            plural="redisshakes",
        )
        return resource

    def load_deployment_object(self, api_client, deployment_name, deployment_namespace):
        api = client.AppsV1Api(
            api_client=api_client
        )
        resource = api.read_namespaced_deployment(
            name=deployment_name,
            namespace=deployment_namespace,
        )
        return resource


class app:
    def __init__(self):
        parser = argparse.ArgumentParser(
            prog='Redis Multi DC Switch',
            description='',
            epilog='')
        parser.add_argument("filename",help="config ini")
        parser.add_argument("-s", "--show", action='store_true',help='show status')
        parser.add_argument("--start_sync", choices=["source", "target"],help="Switch the synchronization direction of \"shake\", supporting two options: source: s->t, target: t->s."),
        parser.add_argument("--failover", action='store_true',help='Failover will shut down the synchronization of "shake".'),
        parser.add_argument("--try_failover", action='store_true',help="Failover will forcefully attempt to shut down the synchronization of \"shake\", regardless of the cluster's connectivity status."),
        self.args = parser.parse_args()

    def list_context(self):
        contexts, active_context = config.list_kube_config_contexts()
        if not contexts:
            print("Cannot find any context in kube-config file.")
            return
        print(contexts)
        contexts = [context['name'] for context in contexts]
        active_index = contexts.index(active_context['name'])
        print(contexts)
        cluster1, first_index = pick(contexts, title="Pick the first context",
                                     default_index=active_index)
        print(cluster1)
        client1 = client.CoreV1Api(
            api_client=config.new_client_from_config(context=cluster1))

    def load_config(self):
        config = configparser.ConfigParser()
        config.read('example.ini')
        config.sections()
        self.cg = config


if __name__ == "__main__":
    active_app = app()
    active_app.load_config()
    if active_app.args.try_failover:
        mdc_redis = multiDCRedisCluster(active_app.cg, skip_err=True)
        mdc_redis.try_failover()
        exit(0)
    mdc_redis = multiDCRedisCluster(active_app.cg, skip_err=False)

    if active_app.args.show:
        mdc_redis.display()
    if active_app.args.start_sync == "source":
        mdc_redis.turn_off_target_shake()
        while mdc_redis.target_shake_deploy.status.ready_replicas == 0:
            mdc_redis.display()
            time.sleep(5)
        mdc_redis.flush_target_redis()
        mdc_redis.turn_on_source_shake()

    if active_app.args.start_sync == "target":
        mdc_redis.turn_off_source_shake()
        while mdc_redis.source_shake_deploy.status.ready_replicas == 0:
            mdc_redis.display()
            time.sleep(5)
        mdc_redis.flush_source_redis()
        mdc_redis.turn_on_target_shake()

    if active_app.args.failover:
        mdc_redis.failover()
