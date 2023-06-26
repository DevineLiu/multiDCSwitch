# Redis容灾切换脚本

## 安装

本地安装

```shell
git clone https://github.com/DevineLiu/multiDCSwitch.git
cd multiDCSwitch
pip install -r requirements.txt
```

docker 启动

```shell
docker pull ghcr.io/devineliu/multidcswitch:v0.0.1
docker run -it -v $HOME/.kube:/root/.kube  ghcr.io/devineliu/multidcswitch:v0.0.1 -h
```

## 配置及使用

1. 配置kubectl 的context,用于控制两集群,参考[context 配置方式](https://kubernetes.io/docs/reference/kubectl/cheatsheet/#kubectl-context-and-configuration)
2. 配置文件格式为ini 

```yaml
[source.context] ;主集群的kubecofig context名
name=admin@x86

[source.redis] ;主集群的redis实例名,命名空间名
name=rc1
namespace=hrliu-redis 

[source.shake] ;主->备集群的shake实例，部署在备集群中
name=shake1
namespace=hrliu-redis

[target.context] ;备集群的kubecofig context名
name=admin@x86

[target.redis] ;备集群的redis实例名
name=rc2
namespace=hrliu-redis

[target.shake] ;备->主的集群的shake实例名，命名空间名，部署在主集群中
name=shake2
namespace=hrliu-redis
```

1. 查看脚本使用说明

```yaml
> python multiDCswitch.py -h
usage: Redis Multi DC Switch [-h] [-s] [--start_sync {source,target}] [--failover] [--try_failover] filename

positional arguments:
  filename

options:
  -h, --help            show this help message and exit
  -s, --show            show status
  --start_sync {source,target}
                        Switch the synchronization direction of "shake", supporting two options: source: s->t, target: t->s.
  --failover            Failover will shut down the synchronization of "shake".
  --try_failover        Failover will forcefully attempt to shut down the synchronization of "shake", regardless of the cluster's connectivity status.
```

1. 查看同步状态

```yaml
> python multiDCswitch.py example.ini -s
                         Redis Multi Data Center Status                         
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃     Source ┃ Source Role ┃ Shake   ┃ Shake Status ┃     Target ┃ Target Role ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ rc1(Ready) │      Master │ >shake1 │              │ rc2(Ready) │       Slave │
├────────────┼─────────────┼─────────┼──────────────┼────────────┼─────────────┤
│ rc1(Ready) │      Master │ <shake2 │              │ rc2(Ready) │       Slave │
└────────────┴─────────────┴─────────┴──────────────┴────────────┴─────────────┘
```

1. 开启主集群同步到备集群，备集群的数据在开始时将被清空。

```yaml
python multiDCswitch.py example.ini -s --start_sync source
```

1. 查看同步状态,正常

```yaml
> python multiDCswitch.py example.ini -s                    
                           Redis Multi Data Center Status                            
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃     Source ┃ Source Role ┃ Shake   ┃ Shake Status      ┃     Target ┃ Target Role ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ rc1(Ready) │      master │ >shake1 │ ->>> syncing >>-- │ rc2(Ready) │       slave │
├────────────┼─────────────┼─────────┼───────────────────┼────────────┼─────────────┤
│ rc1(Ready) │      master │ <shake2 │                   │ rc2(Ready) │       slave │
```

### 容错切换

1. 正常切换，关闭源端和目的端的shake同步

```yaml
> python multiDCswitch.py example.ini --failover
update shake: shake1 replicas 0
update shake: shake2 replicas 0
```

1. 强制尝试切换，关闭源端和目的端的shake同步

```yaml
> python multiDCswitch.py example.ini --failover
update shake: shake1 replicas 0
update shake: shake2 replicas 0
```

1. 开启备集群同步到主集群，主集群的数据将被清空。

```yaml
> python multiDCswitch.py example.ini  --start_sync target
```

查看状态

```yaml
> python multiDCswitch.py example.ini -s                  
                           Redis Multi Data Center Status                           
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃     Source ┃ Source Role ┃ Shake   ┃ Shake Status     ┃     Target ┃ Target Role ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ rc1(Ready) │       slave │ >shake1 │                  │ rc2(Ready) │      master │
├────────────┼─────────────┼─────────┼──────────────────┼────────────┼─────────────┤
│ rc1(Ready) │       slave │ <shake2 │ -<<< syncing <<- │ rc2(Ready) │      master │
└────────────┴─────────────┴─────────┴──────────────────┴────────────┴─────────────┘
```