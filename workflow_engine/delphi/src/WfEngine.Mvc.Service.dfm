object WfEngineGateway: TWfEngineGatewayService
  OldCreateOrder = False
  DisplayName = 'Goliath WfEngine Workflow Gateway'
  AllowPause = True
  AllowStop = True
  OnContinue = ServiceContinue
  OnPause = ServicePause
  OnStart = ServiceStart
  OnStop = ServiceStop
  Height = 150
  Width = 300
end
