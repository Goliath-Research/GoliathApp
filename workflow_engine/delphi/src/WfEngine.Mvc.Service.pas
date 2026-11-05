unit WfEngine.Mvc.Service;

{
  Windows service host for the DMVC workflow gateway (HTTP.sys backend).

  Service name: WfEngineGateway
  - Start    -> open DB-backed gateway state and HTTP.sys listener
  - Pause    -> unregister the HTTP.sys URL and stop accepting requests
                (DB state kept)
  - Continue -> re-register and resume listening
  - Stop     -> close listener and release gateway state

  Install/uninstall with the standard VCL service switches:
    WfEngineSrv /install
    WfEngineSrv /uninstall
}

interface

uses
  Winapi.Windows,
  System.SysUtils,
  System.Classes,
  Vcl.SvcMgr,
  WfEngine.Mvc.Server;

type
  TWfEngineGatewayService = class(TService)
    procedure ServiceStart(Sender: TService; var Started: Boolean);
    procedure ServiceStop(Sender: TService; var Stopped: Boolean);
    procedure ServicePause(Sender: TService; var Paused: Boolean);
    procedure ServiceContinue(Sender: TService; var Continued: Boolean);
  private
    FServer: TWfGatewayServer;
  public
    function GetServiceController: TServiceController; override;
  end;

var
  WfEngineGateway: TWfEngineGatewayService;

implementation

{$R *.dfm}

uses
  WfEngine.GatewayHost;

procedure ServiceController(CtrlCode: DWORD); stdcall;
begin
  WfEngineGateway.Controller(CtrlCode);
end;

function TWfEngineGatewayService.GetServiceController: TServiceController;
begin
  Result := ServiceController;
end;

procedure TWfEngineGatewayService.ServiceStart(Sender: TService; var Started: Boolean);
begin
  Started := False;
  try
    InitGatewayHost(ResolveGatewayConnectionConfig);
    // '+' binds all interfaces; LocalSystem holds the HTTP.sys URL ACL.
    FServer := TWfGatewayServer.Create(ResolveGatewayPort, ResolveGatewayHost('+'));
    FServer.Start;
    Started := True;
  except
    on E: Exception do
    begin
      LogMessage(Format('WfEngineGateway start failed: %s: %s', [E.ClassName, E.Message]));
      FreeAndNil(FServer);
      ShutdownGatewayHost;
    end;
  end;
end;

procedure TWfEngineGatewayService.ServiceStop(Sender: TService; var Stopped: Boolean);
begin
  FreeAndNil(FServer);
  ShutdownGatewayHost;
  Stopped := True;
end;

procedure TWfEngineGatewayService.ServicePause(Sender: TService; var Paused: Boolean);
begin
  if Assigned(FServer) then
    FServer.Stop;
  Paused := True;
end;

procedure TWfEngineGatewayService.ServiceContinue(Sender: TService; var Continued: Boolean);
begin
  if Assigned(FServer) then
    FServer.Start;
  Continued := True;
end;

end.
