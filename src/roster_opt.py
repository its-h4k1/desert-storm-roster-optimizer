# -*- coding: utf-8 -*-
import pandas as pd
try:
    import pulp
except Exception:
    pulp = None

def optimize_rosters(players_df: pd.DataFrame, fairness_weight: float = 0.1):
    names = players_df["PlayerName"].tolist()
    p_start = dict(zip(names, players_df["p_start"]))
    p_sub   = dict(zip(names, players_df["p_sub"]))

    groups = ["A", "B"]
    roles  = ["Start", "Ersatz"]
    req = {("A","Start"):20, ("A","Ersatz"):10, ("B","Start"):20, ("B","Ersatz"):10}

    if pulp is None:
        ranked = sorted(names, key=lambda n: max(p_start[n], p_sub[n]), reverse=True)
        assign = []
        exp_sum = {"A":0.0, "B":0.0}
        quotas = req.copy()
        for n in ranked:
            best_role = "Start" if p_start[n] >= p_sub[n] else "Ersatz"
            order_groups = sorted(groups, key=lambda g: exp_sum[g])
            placed = False
            for g in order_groups:
                if quotas[(g,best_role)] > 0:
                    assign.append((n, g, best_role))
                    quotas[(g,best_role)] -= 1
                    exp_sum[g] += p_start[n] if best_role=="Start" else p_sub[n]
                    placed = True
                    break
            if not placed:
                for g in groups:
                    for r in roles:
                        if quotas[(g,r)] > 0:
                            assign.append((n,g,r))
                            quotas[(g,r)] -= 1
                            exp_sum[g] += p_start[n] if r=="Start" else p_sub[n]
                            placed = True
                            break
                    if placed: break
            if all(v==0 for v in quotas.values()):
                break
        out = pd.DataFrame(assign, columns=["PlayerName","Group","Role"])
        return out

    m = pulp.LpProblem("RosterOptimization", pulp.LpMaximize)
    x = {}
    for n in names:
        for g in groups:
            for r in roles:
                x[(n,g,r)] = pulp.LpVariable(f"x_{abs(hash(n))%10**6}_{g}_{r}", lowBound=0, upBound=1, cat="Binary")

    for n in names:
        m += pulp.lpSum([x[(n,g,r)] for g in groups for r in roles]) <= 1

    for g in groups:
        for r in roles:
            m += pulp.lpSum([x[(n,g,r)] for n in names]) == req[(g,r)]

    exp_g = {}
    for g in groups:
        exp_g[g] = pulp.lpSum([
            x[(n,g,"Start")] * p_start[n] + x[(n,g,"Ersatz")] * p_sub[n] for n in names
        ])

    total_expected = pulp.lpSum([exp_g[g] for g in groups])
    z = pulp.LpVariable("z_min_group_expectation", lowBound=0)
    for g in groups:
        m += z <= exp_g[g]
    m += total_expected + fairness_weight * z

    m.solve(pulp.PULP_CBC_CMD(msg=False))

    rows = []
    for n in names:
        for g in groups:
            for r in roles:
                if pulp.value(x[(n,g,r)]) > 0.5:
                    rows.append({"PlayerName": n, "Group": g, "Role": r})
    out = pd.DataFrame(rows)
    return out
