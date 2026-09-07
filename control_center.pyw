from desktop_control_center import ControlCenterApp, main
from control_center_safety_view import install_real_safety_view


install_real_safety_view(ControlCenterApp)
raise SystemExit(main())
