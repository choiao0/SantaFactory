"""pytest 6(pythonpath 옵션 없음)에서도 `import edge` 가 되게 t3_amr 을 sys.path 에 넣는다."""
import os
import sys

T3AMR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if T3AMR not in sys.path:
    sys.path.insert(0, T3AMR)
