"""Complete identical wires in parallel; strands describe one such wire."""
import math


def count(parameters, side):
    key='parallel_wires_'+side
    value=parameters.get(key,1)
    if (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)
            or int(value)!=value or not 1<=value<=10000000):
        raise ValueError(key+' 线圈并绕数必须为 1–10⁷ 的整数，表示相同整根线的并联根数')
    return int(value)
