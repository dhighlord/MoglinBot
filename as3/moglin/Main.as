package moglin
{
	import flash.display.Loader;
	import flash.display.LoaderInfo;
	import flash.display.MovieClip;
	import flash.display.Sprite;
	import flash.display.Stage;
	import flash.display.StageAlign;
	import flash.display.StageScaleMode;
	import flash.events.Event;
	import flash.events.IOErrorEvent;
	import flash.events.MouseEvent;
	import flash.events.SecurityErrorEvent;
	import flash.events.ProgressEvent;
	import flash.external.ExternalInterface;
	import flash.net.Socket;
	import flash.net.URLLoader;
	import flash.net.URLRequest;
	import flash.system.ApplicationDomain;
	import flash.system.LoaderContext;
	import flash.system.Security;
	import flash.system.SecurityDomain;
	import flash.text.TextField;
	import flash.text.TextFieldAutoSize;
	import flash.text.TextFormat;
	import flash.utils.ByteArray;
	import mx.utils.StringUtil;
	
	/**
	 * Moglin Bot wrapper loader.
	 *
	 * This SWF loads the real AQW game client and overlays a small in-game
	 * bot GUI on top of it (inside the same window). The GUI:
	 *   - shows connection/status info
	 *   - provides Start/Stop buttons
	 *   - listens for automation commands from the game client itself
	 *
	 * Automation integration: the game's own `sfc` (SmartFox client) object is
	 * exposed once the game loads; the Python side injects packets through
	 * ExternalInterface callbacks (sendClientPacket) exactly like rBot did.
	 */
	public class Main extends MovieClip
	{
		public static var instance:Main;
		
		private var sURL:String = "https://game.aq.com/game/";
		private var versionUrl:String = sURL + "api/data/gameversion";
		private var loginURL:String = sURL + "api/login/now";
		private var sFile:String;
		private var sBG:String = "Generic2.swf";
		private var isEU:Boolean = false;
		private var urlLoader:URLLoader;
		private var loader:Loader;
		private var vars:Object;
		private var sTitle:String = "Moglin Bot";
		
		private var stg:Stage;
		private var gameDomain:ApplicationDomain;
		private var game:Object;
		
		// Overlay GUI
		private var gui:Sprite;
		private var statusText:TextField;
		private var startBtn:Sprite;
		private var stopBtn:Sprite;
		
		// Python bridge socket (localhost control channel)
		private var ctlSocket:Socket;
		private var ctlBuffer:ByteArray;
		private const CTL_HOST:String = "127.0.0.1";
		private const CTL_PORT:int = 5587;
		
		public function Main()
		{
			String.prototype.trim = function():String
			{
				return this.replace(/^\s+|\s+$/g, "");
			};
			
			Main.instance = this;
			
			if (stage)
				init();
			else
				addEventListener(Event.ADDED_TO_STAGE, init);
		}
		
		public static function loadGame(swfFile:String):void
		{
			if (swfFile != null)
				Main.instance.sFile = swfFile;
			
			Main.instance.onAddedToStage();
		}
		
		private function init(e:Event = null):void
		{
			removeEventListener(Event.ADDED_TO_STAGE, init);
			Security.allowDomain("*");
			
			// Register ExternalInterface callbacks for the host.
			if (ExternalInterface.available)
			{
				ExternalInterface.addCallback("loadClient", Main.loadGame);
				ExternalInterface.addCallback("sendClientPacket", sendClientPacket);
				ExternalInterface.addCallback("isLoggedIn", isLoggedIn);
				ExternalInterface.addCallback("getGameObject", getGameObject);
				ExternalInterface.addCallback("callGameFunction", callGameFunction);
				
				ExternalInterface.call("requestLoadGame");
			}
		}
		
		private function onAddedToStage():void
		{
			Security.allowDomain("*");
			urlLoader = new URLLoader();
			urlLoader.addEventListener(Event.COMPLETE, onDataComplete);
			urlLoader.load(new URLRequest(versionUrl + "?ver=" + Math.random()));
		}
		
		private function onDataComplete(event:Event):void
		{
			urlLoader.removeEventListener(Event.COMPLETE, onDataComplete);
			try
			{
				vars = JSON.parse(event.target.data);
				sFile = vars.sFile + "?ver=" + Math.random();
				loadGameSWF();
			}
			catch (e:Error)
			{
				trace("Moglin: version parse failed: " + e.message);
			}
		}
		
		private function loadGameSWF():void
		{
			loader = new Loader();
			loader.contentLoaderInfo.addEventListener(Event.COMPLETE, onGameLoaded);
			var context:LoaderContext = new LoaderContext();
			context.securityDomain = SecurityDomain.currentDomain;
			loader.load(new URLRequest(sURL + "gamefiles/" + sFile), context);
		}
		
		private function onGameLoaded(event:Event):void
		{
			loader.contentLoaderInfo.removeEventListener(Event.COMPLETE, onGameLoaded);
			
			stg = stage;
			stg.removeChildAt(0);
			game = stg.addChild(loader.content);
			stg.scaleMode = StageScaleMode.SHOW_ALL;
			stg.align = StageAlign.TOP;
			
			for (var param:String in root.loaderInfo.parameters)
			{
				game.params[param] = root.loaderInfo.parameters[param];
			}
			
			game.params.vars = vars;
			game.params.sURL = sURL;
			game.params.sTitle = sTitle;
			game.params.sBG = sBG;
			game.params.isEU = isEU;
			game.params.loginURL = loginURL;
			game.params.isWeb = false; // desktop mode (AQW Pocket does this)
			
			gameDomain = LoaderInfo(event.target).applicationDomain;
			
			// Add the in-game overlay GUI on top of the game.
			createGUI();
			
			// Connect to the Python control channel for automation.
			connectControl();
			
			trace("Moglin: game loaded");
			if (ExternalInterface.available)
				ExternalInterface.call("loaded");
		}
		
		// ---------------------------------------------------------------------
		// Python control channel (localhost socket)
		// ---------------------------------------------------------------------
		private function connectControl():void
		{
			ctlBuffer = new ByteArray();
			ctlSocket = new Socket();
			ctlSocket.addEventListener(Event.CONNECT, onCtlConnect);
			ctlSocket.addEventListener(ProgressEvent.SOCKET_DATA, onCtlData);
			ctlSocket.addEventListener(IOErrorEvent.IO_ERROR, onCtlError);
			ctlSocket.addEventListener(SecurityErrorEvent.SECURITY_ERROR, onCtlError);
			ctlSocket.addEventListener(Event.CLOSE, onCtlClose);
			try
			{
				ctlSocket.connect(CTL_HOST, CTL_PORT);
			}
			catch (e:Error)
			{
				setStatus("Control offline: " + e.message);
			}
		}
		
		private function onCtlConnect(e:Event):void
		{
			setStatus("Connected to Moglin Bot");
			ctlSend('{"cmd":"hello"}\n');
		}
		
		private function onCtlData(e:ProgressEvent):void
		{
			while (ctlSocket.bytesAvailable > 0)
			{
				var line:String = ctlSocket.readUTFBytes(ctlSocket.bytesAvailable);
				// Process line-by-line (commands are JSON, newline-delimited).
				var lines:Array = line.split("\n");
				for each (var cmd:String in lines)
				{
					cmd = StringUtil.trim(cmd);
					if (cmd.length == 0)
						continue;
					handleCommand(cmd);
				}
			}
		}
		
		private function handleCommand(json:String):void
		{
			try
			{
				var obj:Object = JSON.parse(json);
				switch (obj.cmd)
				{
					case "status":
						ctlSend('{"cmd":"status","loggedIn":' + isLoggedIn() + ',"map":' + JSON.stringify(getGameObject("world.strMapName")) + '}\n');
						break;
					case "packet":
						sendClientPacket(String(obj.packet), obj.type ? String(obj.type) : "str");
						break;
					case "setStatus":
						setStatus(String(obj.message));
						break;
				}
			}
			catch (e:Error)
			{
				trace("Moglin: bad command: " + e.message);
			}
		}
		
		private function ctlSend(msg:String):void
		{
			if (ctlSocket && ctlSocket.connected)
			{
				ctlSocket.writeUTFBytes(msg);
				ctlSocket.flush();
			}
		}
		
		private function onCtlError(e:Event):void
		{
			setStatus("Control offline (retrying...)");
			// Retry connection after a delay.
			var retry:Function = function():void {
				if (ctlSocket && !ctlSocket.connected)
				{
					try { ctlSocket.connect(CTL_HOST, CTL_PORT); }
					catch (err:Error) {}
				}
			};
			var timer:flash.utils.Timer = new flash.utils.Timer(3000, 1);
			timer.addEventListener(flash.events.TimerEvent.TIMER, function(te:flash.events.TimerEvent):void { retry(); });
			timer.start();
		}
		
		private function onCtlClose(e:Event):void
		{
			setStatus("Control disconnected");
		}
		
		// ---------------------------------------------------------------------
		// In-game overlay GUI
		// ---------------------------------------------------------------------
		private function createGUI():void
		{
			gui = new Sprite();
			stg.addChild(gui);
			
			// Semi-transparent panel at the top-right corner.
			var panel:Sprite = new Sprite();
			panel.graphics.beginFill(0x101418, 0.85);
			panel.graphics.lineStyle(1, 0x4f8cff, 0.6);
			panel.graphics.drawRoundRect(0, 0, 190, 120, 8, 8);
			panel.graphics.endFill();
			gui.addChild(panel);
			
			var fmt:TextFormat = new TextFormat("Arial", 11, 0xE8EAF2, true);
			var titleFmt:TextFormat = new TextFormat("Arial", 13, 0x4f8cff, true);
			
			var title:TextField = new TextField();
			title.defaultTextFormat = titleFmt;
			title.text = "Moglin Bot";
			title.autoSize = TextFieldAutoSize.LEFT;
			title.selectable = false;
			title.mouseEnabled = false;
			title.x = 12;
			title.y = 10;
			gui.addChild(title);
			
			statusText = new TextField();
			statusText.defaultTextFormat = fmt;
			statusText.text = "Status: loading...";
			statusText.autoSize = TextFieldAutoSize.LEFT;
			statusText.selectable = false;
			statusText.mouseEnabled = false;
			statusText.x = 12;
			statusText.y = 34;
			gui.addChild(statusText);
			
			startBtn = makeButton("Start Bot", 0x22C55E);
			startBtn.x = 12;
			startBtn.y = 62;
			startBtn.addEventListener(MouseEvent.CLICK, onStartClick);
			gui.addChild(startBtn);
			
			stopBtn = makeButton("Stop Bot", 0xEF4444);
			stopBtn.x = 100;
			stopBtn.y = 62;
			stopBtn.addEventListener(MouseEvent.CLICK, onStopClick);
			gui.addChild(stopBtn);
			
			// Keep the GUI above the game.
			stg.setChildIndex(gui, stg.numChildren - 1);
			
			setStatus("Ready. Waiting for login...");
		}
		
		private function makeButton(label:String, color:uint):Sprite
		{
			var btn:Sprite = new Sprite();
			btn.graphics.beginFill(color, 0.9);
			btn.graphics.drawRoundRect(0, 0, 78, 28, 6, 6);
			btn.graphics.endFill();
			btn.buttonMode = true;
			btn.useHandCursor = true;
			
			var tf:TextField = new TextField();
			tf.defaultTextFormat = new TextFormat("Arial", 11, 0xFFFFFF, true);
			tf.text = label;
			tf.autoSize = TextFieldAutoSize.CENTER;
			tf.selectable = false;
			tf.mouseEnabled = false;
			tf.x = 6;
			tf.y = 6;
			btn.addChild(tf);
			
			return btn;
		}
		
		private function setStatus(msg:String):void
		{
			if (statusText)
				statusText.text = "Status: " + msg;
		}
		
		private function onStartClick(e:MouseEvent):void
		{
			setStatus("Bot started");
			trace("Moglin: start clicked");
			ctlSend('{"cmd":"botStart"}\n');
			if (ExternalInterface.available)
				ExternalInterface.call("botStart");
		}
		
		private function onStopClick(e:MouseEvent):void
		{
			setStatus("Bot stopped");
			trace("Moglin: stop clicked");
			ctlSend('{"cmd":"botStop"}\n');
			if (ExternalInterface.available)
				ExternalInterface.call("botStop");
		}
		
		// ---------------------------------------------------------------------
		// Bridge functions (called by the host via ExternalInterface)
		// ---------------------------------------------------------------------
		public function sendClientPacket(packet:String, type:String = "str"):void
		{
			if (!game || !game.sfc)
				return;
			
			switch (type)
			{
				case "str":
					game.sfc.send(packet);
					break;
				case "json":
					game.sfc.send(JSON.parse(packet));
					break;
				case "xml":
					game.sfc.send(new XML(packet));
					break;
			}
		}
		
		public function isLoggedIn():Boolean
		{
			return game != null && game.sfc != null && game.sfc.isConnected;
		}
		
		public function getGameObject(path:String):String
		{
			if (!game)
				return "null";
			var obj:Object = game;
			var parts:Array = path.split(".");
			for each (var part:String in parts)
			{
				if (obj == null)
					break;
				obj = obj[part];
			}
			return JSON.stringify(obj);
		}
		
		public function callGameFunction(path:String, ... args):String
		{
			if (!game)
				return "null";
			var parts:Array = path.split(".");
			var funcName:String = parts.pop();
			var obj:Object = game;
			for each (var part:String in parts)
			{
				if (obj == null)
					break;
				obj = obj[part];
			}
			if (obj && obj[funcName] is Function)
			{
				var func:Function = obj[funcName] as Function;
				return JSON.stringify(func.apply(null, args));
			}
			return "null";
		}
	}
}
