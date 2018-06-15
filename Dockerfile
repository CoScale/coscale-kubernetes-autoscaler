FROM python:3

LABEL com.coscale.monitoring='[{"PluginType":"LOGPLUGIN","Configuration":{"MATCH":["\"/dev/stdout\" \"COUNTER\" \"Autoscaler checking\" \"INFO Checking\" \"#\"","\"/dev/stdout\" \"COUNTER\" \"Autoscaler scaling\" \"INFO Scaling\" \"*\"","\"/dev/stdout\" \"COUNTER\" \"Autoscaler errors\" \"ERROR\" \"#\""]}}]'

RUN pip install kubernetes==6.0.0 urllib3==1.22

ADD https://github.com/CoScale/coscale-cli/releases/download/3.6.0/coscale-cli /opt/coscale/autoscaler/

COPY src /opt/coscale/autoscaler

RUN chmod +x /opt/coscale/autoscaler/coscale-cli && chmod -R g=u /opt/coscale/

CMD [ "/opt/coscale/autoscaler/entrypoint.sh" ]
