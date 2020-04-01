import numpy as np
import numba
from warnings import warn
from collections import namedtuple


EPSILON = 2.2204460492503131e-15
NET_SUPPLY_ERROR_TOLERANCE = 1e-8

## Defaults to double for everythig in POT
INFINITY = np.finfo(np.float64).max
INF = np.finfo(np.float64).max
MAX = np.finfo(np.float64).max

# Problem Types
OPTIMAL = 0
MAX_ITER_REACHED = -1
UNBOUNDED = -2
INFEASIBLE = -3

# Arc States
STATE_UPPER = -1
STATE_TREE = 0
STATE_LOWER = 1

INVALID = -1

SpanningTree = namedtuple(
    "SpanningTree",
    [
        "parent",  # int array
        "pred",  # int array
        "thread",  # int array
        "rev_thread",  # int array
        "succ_num",  # int array
        "last_succ",  # int array
        "forward",  # bool array
        "state",  # state array
        "root",  # int
    ],
)
PivotBlock = namedtuple(
    "PivotBlock",
    [
        "block_size",  # int
        "next_arc",  # int array length 1 for updatability
        "search_arc_num",  # int
    ],
)
DiGraph = namedtuple(
    "DiGraph",
    [
        "n_nodes",  # int
        "n_arcs",  # int
        "n",  # int
        "m",  # int
        "use_arc_mixing",  # bool
        "num_total_big_subsequence_numbers",  # int
        "subsequence_length",  # int
        "num_big_subsequences",  # int
        "mixing_coeff",
    ],
)
NodeArcData = namedtuple(
    "NodeArcData",
    [
        "cost",  # double array
        "supply",  # double array
        "flow",  # double array
        "pi",  # double array
        "source",  # unsigned int array
        "target",  # unsigned int array
    ],
)

# locals: c, min, e, cnt, a
# modifies _in_arc, _next_arc,
@numba.njit()
def find_entering_arc(
    pivot_block, state_vector, node_arc_data, in_arc,
):
    min = 0
    cnt = pivot_block.block_size

    # Pull from tuple for quick reference
    cost = node_arc_data.cost
    pi = node_arc_data.pi
    source = node_arc_data.source
    target = node_arc_data.target

    for e in range(pivot_block.next_arc[0], pivot_block.search_arc_num):  # (e =
        # _next_arc; e !=
        # _search_arc_num; ++e) {
        c = state_vector[e] * (cost[e] + pi[source[e]] - pi[target[e]])
        if c < min:
            min = c
            in_arc = e

        cnt -= 1
        if cnt == 0:
            if np.fabs(pi[source[in_arc]]) > np.fabs(pi[target[in_arc]]):
                a = np.fabs(pi[source[in_arc]])
            else:
                a = np.fabs(pi[target[in_arc]])

            if a <= np.fabs(cost[in_arc]):
                a = np.fabs(cost[in_arc])

            if min < -(EPSILON * a):
                pivot_block.next_arc[0] = e
                return True, in_arc
            else:
                cnt = pivot_block.block_size
            # a=fabs(_pi[_source[_in_arc]])>fabs(_pi[_target[_in_arc]]) ? fabs(_pi[_source[_in_arc]]):fabs(_pi[_target[_in_arc]]);
            # a=a>fabs(_cost[_in_arc])?a:fabs(_cost[_in_arc]);
            # if (min <  -EPSILON*a) goto search_end;
            # cnt = _block_size;

    for e in range(pivot_block.next_arc[0]):  # (e = 0; e != _next_arc; ++e) {
        c = state_vector[e] * (cost[e] + pi[source[e]] - pi[target[e]])
        if c < min:
            min = c
            in_arc = e

        cnt -= 1
        if cnt == 0:
            if np.fabs(pi[source[in_arc]]) > np.fabs(pi[target[in_arc]]):
                a = np.fabs(pi[source[in_arc]])
            else:
                a = np.fabs(pi[target[in_arc]])

            if a <= np.fabs(cost[in_arc]):
                a = np.fabs(cost[in_arc])

            if min < -(EPSILON * a):
                pivot_block.next_arc[0] = e
                return True, in_arc
            else:
                cnt = pivot_block.block_size
            # a=fabs(_pi[_source[_in_arc]])>fabs(_pi[_target[_in_arc]]) ? fabs(_pi[_source[_in_arc]]):fabs(_pi[_target[_in_arc]]);
            # a=a>fabs(_cost[_in_arc])?a:fabs(_cost[_in_arc]);
            # if (min <  -EPSILON*a) goto search_end;
            # cnt = _block_size;

    # assert(pivot_block.next_arc[0] == 0 or e == pivot_block.next_arc[0] - 1)

    if np.fabs(pi[source[in_arc]]) > np.fabs(pi[target[in_arc]]):
        a = np.fabs(pi[source[in_arc]])
    else:
        a = np.fabs(pi[target[in_arc]])

    if a <= np.fabs(cost[in_arc]):
        a = np.fabs(cost[in_arc])

    if min >= -(EPSILON * a):
        return False, in_arc
    # a=fabs(_pi[_source[_in_arc]])>fabs(_pi[_target[_in_arc]]) ? fabs(_pi[_source[_in_arc]]):fabs(_pi[_target[_in_arc]]);
    # a=a>fabs(_cost[_in_arc])?a:fabs(_cost[_in_arc]);
    # if (min >=  -EPSILON*a) return false;

    # _next_arc = e # This is not required as we don't use the goto
    # And the last for loop ends on e = _next_arc
    return True, in_arc


# Find the join node
# Operates with graph (_source, _target) and MST (_succ_num, _parent, in_arc) data
# locals: u, v
# modifies: join
@numba.njit()
def find_join_node(source, target, succ_num, parent, in_arc):
    u = source[in_arc]
    v = target[in_arc]
    while u != v:
        if succ_num[u] < succ_num[v]:
            u = parent[u]
        else:
            v = parent[v]

    join = u

    return join


# Find the leaving arc of the cycle and returns true if the
# leaving arc is not the same as the entering arc
# locals: first, second, result, d, e
# modifies: u_in, v_in, u_out, delta
@numba.njit()
def find_leaving_arc(
    join, in_arc, node_arc_data, spanning_tree,
):
    source = node_arc_data.source
    target = node_arc_data.target
    flow = node_arc_data.flow

    state = spanning_tree.state
    forward = spanning_tree.forward
    pred = spanning_tree.pred
    parent = spanning_tree.parent

    # TODO: leave this unchanged by passing it in?
    u_out = -1  # May not be set, but we need to return something?

    # Initialize first and second nodes according to the direction
    # of the cycle
    if state[in_arc] == STATE_LOWER:
        first = source[in_arc]
        second = target[in_arc]
    else:
        first = target[in_arc]
        second = source[in_arc]

    delta = INF
    result = 0

    # Search the cycle along the path form the first node to the root
    # for (int u = first; u != join; u = _parent[u]) {
    u = first
    while u != join:
        e = pred[u]
        if forward[u]:
            d = flow[e]
        else:
            d = INF

        if d < delta:
            delta = d
            u_out = u
            result = 1

        u = parent[u]

    # Search the cycle along the path form the second node to the root
    # for (int u = second; u != join; u = _parent[u]) {
    u = second
    while u != join:
        e = pred[u]
        if forward[u]:
            d = INF
        else:
            d = flow[e]

        if d <= delta:
            delta = d
            u_out = u
            result = 2

        u = parent[u]

    if result == 1:
        u_in = first
        v_in = second
    else:
        u_in = second
        v_in = first

    return result != 0, (u_in, v_in, u_out, delta)


# Change _flow and _state vectors
# locals: val, u
# modifies: _state, _flow
@numba.njit()
def update_flow(
    change, join, delta, u_out, node_arc_data, spanning_tree, in_arc,
):
    source = node_arc_data.source
    target = node_arc_data.target
    flow = node_arc_data.flow

    state = spanning_tree.state
    pred = spanning_tree.pred
    parent = spanning_tree.parent
    forward = spanning_tree.forward

    # Augment along the cycle
    if delta > 0:
        val = state[in_arc] * delta
        flow[in_arc] += val
        # for (int u = _source[in_arc]; u != join; u = _parent[u]) {
        u = source[in_arc]
        while u != join:
            if forward[u]:
                flow[pred[u]] -= val
            else:
                flow[pred[u]] += val

            u = parent[u]

        # for (int u = _target[in_arc]; u != join; u = _parent[u]) {
        u = target[in_arc]
        while u != join:
            if forward[u]:
                flow[pred[u]] += val
            else:
                flow[pred[u]] -= val

            u = parent[u]

    # Update the state of the entering and leaving arcs
    if change:
        state[in_arc] = STATE_TREE
        if flow[pred[u_out]] == 0:
            state[pred[u_out]] = STATE_LOWER
        else:
            state[pred[u_out]] = STATE_UPPER
    else:
        state[in_arc] = -state[in_arc]


# Update the tree structure
# locals: u, w, old_rev_thread, old_succ_num, old_last_succ, tmp_sc, tmp_ls
# more locals: up_limit_in, up_limit_out, _dirty_revs
# modifies: v_out, _thread, _rev_thread, _parent, _last_succ,
# modifies: _pred, _forward, _succ_num
@numba.njit()
def update_spanning_tree(
    spanning_tree, v_in, u_in, u_out, join, in_arc, source,
):

    parent = spanning_tree.parent
    thread = spanning_tree.thread
    rev_thread = spanning_tree.rev_thread
    succ_num = spanning_tree.succ_num
    last_succ = spanning_tree.last_succ
    forward = spanning_tree.forward
    pred = spanning_tree.pred

    old_rev_thread = rev_thread[u_out]
    old_succ_num = succ_num[u_out]
    old_last_succ = last_succ[u_out]
    v_out = parent[u_out]

    u = last_succ[u_in]  # the last successor of u_in
    right = thread[u]  # the node after it

    # Handle the case when old_rev_thread equals to v_in
    # (it also means that join and v_out coincide)
    if old_rev_thread == v_in:
        last = thread[last_succ[u_out]]
    else:
        last = thread[v_in]

    # Update _thread and _parent along the stem nodes (i.e. the nodes
    # between u_in and u_out, whose parent have to be changed)
    thread[v_in] = stem = u_in
    dirty_revs = []
    dirty_revs.append(v_in)
    par_stem = v_in
    while stem != u_out:
        # Insert the next stem node into the thread list
        new_stem = parent[stem]
        thread[u] = new_stem
        dirty_revs.append(u)

        # Remove the subtree of stem from the thread list
        w = rev_thread[stem]
        thread[w] = right
        rev_thread[right] = w

        # Change the parent node and shift stem nodes
        parent[stem] = par_stem
        par_stem = stem
        stem = new_stem

        # Update u and right
        if last_succ[stem] == last_succ[par_stem]:
            u = rev_thread[par_stem]
        else:
            u = last_succ[stem]

        right = thread[u]

    parent[u_out] = par_stem
    thread[u] = last
    rev_thread[last] = u
    last_succ[u_out] = u

    # Remove the subtree of u_out from the thread list except for
    # the case when old_rev_thread equals to v_in
    # (it also means that join and v_out coincide)
    if old_rev_thread != v_in:
        thread[old_rev_thread] = right
        rev_thread[right] = old_rev_thread

    # Update _rev_thread using the new _thread values
    # for (int i = 0; i != int(_dirty_revs.size()); ++i) {
    for i in range(len(dirty_revs)):
        u = dirty_revs[i]
        rev_thread[thread[u]] = u

    # Update _pred, _forward, _last_succ and _succ_num for the
    # stem nodes from u_out to u_in
    tmp_sc = 0
    tmp_ls = last_succ[u_out]
    u = u_out
    while u != u_in:
        w = parent[u]
        pred[u] = pred[w]
        forward[u] = not forward[w]
        tmp_sc += succ_num[u] - succ_num[w]
        succ_num[u] = tmp_sc
        last_succ[w] = tmp_ls
        u = w

    pred[u_in] = in_arc
    forward[u_in] = u_in == source[in_arc]
    succ_num[u_in] = old_succ_num

    # Set limits for updating _last_succ form v_in and v_out
    # towards the root
    up_limit_in = -1
    up_limit_out = -1
    if last_succ[join] == v_in:
        up_limit_out = join
    else:
        up_limit_in = join

    # Update _last_succ from v_in towards the root
    # for (u = v_in; u != up_limit_in && _last_succ[u] == v_in;
    #      u = _parent[u]) {
    u = v_in
    while u != up_limit_in and last_succ[u] == v_in:
        last_succ[u] = last_succ[u_out]
        u = parent[u]

    # Update _last_succ from v_out towards the root
    if join != old_rev_thread and v_in != old_rev_thread:
        # for (u = v_out; u != up_limit_out && _last_succ[u] == old_last_succ;
        #      u = _parent[u]) {
        u = v_out
        while u != up_limit_out and last_succ[u] == old_last_succ:
            last_succ[u] = old_rev_thread
            u = parent[u]

    else:
        # for (u = v_out; u != up_limit_out && _last_succ[u] == old_last_succ;
        #      u = _parent[u]) {
        u = v_out
        while u != up_limit_out and last_succ[u] == old_last_succ:
            last_succ[u] = last_succ[u_out]
            u = parent[u]

    # Update _succ_num from v_in to join
    # for (u = v_in; u != join; u = _parent[u]) {
    u = v_in
    while u != join:
        succ_num[u] += old_succ_num
        u = parent[u]

    # Update _succ_num from v_out to join
    # for (u = v_out; u != join; u = _parent[u]) {
    u = v_out
    while u != join:
        succ_num[u] -= old_succ_num
        u = parent[u]


# Update potentials
# locals: sigma, end
# modifies: _pi
@numba.njit()
def update_potential(u_in, v_in, pi, cost, spanning_tree):

    thread = spanning_tree.thread
    pred = spanning_tree.pred
    forward = spanning_tree.forward
    last_succ = spanning_tree.last_succ

    if forward[u_in]:
        sigma = pi[v_in] - pi[u_in] - cost[pred[u_in]]
    else:
        sigma = pi[v_in] - pi[u_in] + cost[pred[u_in]]

    # Update potentials in the subtree, which has been moved
    # for (int u = u_in; u != end; u = _thread[u]) {
    end = thread[last_succ[u_in]]
    u = u_in
    while u != end:
        pi[u] += sigma
        u = thread[u]


# If we have mixed arcs (for better random access)
# we need a more complicated function to get the ID of a given arc
@numba.njit()
def arc_id(arc, graph):
    k = graph.n_arcs - arc - 1
    if graph.use_arc_mixing:
        smallv = (k > graph.num_total_big_subsequence_numbers) & 1
        k -= graph.num_total_big_subsequence_numbers * smallv
        subsequence_length2 = graph.subsequence_length - smallv
        subsequence_num = (
            k // subsequence_length2
        ) + graph.num_big_subsequences * smallv
        subsequence_offset = (k % subsequence_length2) * graph.mixing_coeff

        return subsequence_offset + subsequence_num
    else:
        return k


# Heuristic initial pivots
# locals: curr, total, supply_nodes, demand_nodes, u
# modifies:
@numba.njit()
def construct_initial_pivots(sum_supply, graph, node_arc_data, spanning_tree):

    cost = node_arc_data.cost
    pi = node_arc_data.pi
    source = node_arc_data.source
    target = node_arc_data.target
    supply = node_arc_data.supply

    n1 = graph.n
    n2 = graph.m
    node_num = graph.n_nodes
    n_arcs = graph.n_arcs

    state = spanning_tree.state

    curr = 0
    total = 0
    supply_nodes = []
    demand_nodes = []

    # Node u; _graph.first(u);
    # for (; u != INVALIDNODE; _graph.next(u)) {
    for u in range(node_num - 1, -1, -1):
        curr = supply[node_num - u - 1]  # _node_id(u)
        if curr > 0:
            total += curr
            supply_nodes.append(u)
        elif curr < 0:
            demand_nodes.append(u)

    if sum_supply > 0:
        total -= sum_supply

    if total <= 0:
        return True, -1

    arc_vector = []
    if sum_supply >= 0:
        if len(supply_nodes) == 1 and len(demand_nodes) == 1:
            # Perform a reverse graph search from the sink to the source
            # typename GR::template NodeMap<bool> reached(_graph, false);
            reached = np.zeros(node_num, dtype=np.bool_)
            s = supply_nodes[0]
            t = demand_nodes[0]
            stack = []
            reached[t] = True
            stack.append(t)
            while len(stack) > 0:
                u = stack[-1]
                v = stack[-1]
                stack.pop(-1)
                if v == s:
                    break

                # Arc a; _graph.firstIn(a, v);
                # for (; a != INVALID; _graph.nextIn(a)) {
                first_arc = n_arcs + v - node_num if v >= n1 else -1
                for a in range(first_arc, -1, -n2):
                    u = a // n2
                    if reached[u]:
                        continue

                    j = arc_id(a, graph)
                    if INF >= total:
                        arc_vector.append(j)
                        reached[u] = True
                        stack.append(u)

        else:
            # Find the min. cost incomming arc for each demand node
            # for (int i = 0; i != int(demand_nodes.size()); ++i) {
            for i in range(len(demand_nodes)):
                v = demand_nodes[i]
                c = MAX
                min_cost = MAX
                min_arc = INVALID
                # Arc a; _graph.firstIn(a, v);
                # for (; a != INVALID; _graph.nextIn(a)) {
                first_arc = n_arcs + v - node_num if v >= n1 else -1
                for a in range(first_arc, -1, -n2):
                    c = cost[arc_id(a, graph)]
                    if c < min_cost:
                        min_cost = c
                        min_arc = a

                if min_arc != INVALID:
                    arc_vector.append(arc_id(min_arc, graph))

    else:
        # Find the min. cost outgoing arc for each supply node
        # for (int i = 0; i != int(supply_nodes.size()); ++i) {
        for i in range(len(supply_nodes)):
            u = supply_nodes[i]
            c = MAX
            min_cost = MAX
            min_arc = INVALID
            # Arc a; _graph.firstOut(a, u);
            # for (; a != INVALID; _graph.nextOut(a)) {
            a = (u + 1) * n2 - 1 if u <= n1 else -1
            while a % n2 != 0 and a >= 0:
                c = cost[arc_id(a, graph)]
                if c < min_cost:
                    min_cost = c
                    min_arc = a

                a -= 1

            if min_arc != INVALID:
                arc_vector.append(arc_id(min_arc, graph))

    # Perform heuristic initial pivots
    # for (int i = 0; i != int(arc_vector.size()); ++i) {
    in_arc = -1
    for i in range(len(arc_vector)):
        in_arc = arc_vector[i]
        # l'erreur est probablement ici... ???
        if (
            state[in_arc] * (cost[in_arc] + pi[source[in_arc]] - pi[target[in_arc]])
            >= 0
        ):
            continue

        join = find_join_node(
            source, target, spanning_tree.succ_num, spanning_tree.parent, in_arc
        )
        change, (u_in, v_in, u_out, delta) = find_leaving_arc(
            join, in_arc, node_arc_data, spanning_tree
        )
        if delta >= MAX:
            return False, in_arc

        update_flow(change, join, delta, u_out, node_arc_data, spanning_tree, in_arc)
        if change:
            update_spanning_tree(spanning_tree, v_in, u_in, u_out, join, in_arc, source)
            update_potential(u_in, v_in, pi, cost, spanning_tree)

    return True, in_arc


@numba.njit()
def allocate_graph_structures(n, m, use_arc_mixing=True):

    # Size bipartite graph
    n_nodes = n + m
    n_arcs = n * m

    # Resize vectors
    all_node_num = n_nodes + 1
    max_arc_num = n_arcs + 2 * n_nodes
    root = n_nodes

    source = np.zeros(max_arc_num, dtype=np.uint32)
    target = np.zeros(max_arc_num, dtype=np.uint32)
    cost = np.zeros(max_arc_num, dtype=np.float64)
    supply = np.zeros(all_node_num, dtype=np.float64)
    flow = np.zeros(max_arc_num, dtype=np.float64)
    pi = np.zeros(all_node_num, dtype=np.float64)

    parent = np.zeros(all_node_num, dtype=np.int32)
    pred = np.zeros(all_node_num, dtype=np.int32)
    forward = np.zeros(all_node_num, dtype=np.bool_)
    thread = np.zeros(all_node_num, dtype=np.int32)
    rev_thread = np.zeros(all_node_num, dtype=np.int32)
    succ_num = np.zeros(all_node_num, dtype=np.int32)
    last_succ = np.zeros(all_node_num, dtype=np.int32)
    state = np.zeros(max_arc_num, dtype=np.int8)

    # _arc_mixing=false;
    if use_arc_mixing:
        # Store the arcs in a mixed order
        k = max(np.int32(np.sqrt(n_arcs)), 10)
        mixingCoeff = k
        subsequence_length = (n_arcs // mixingCoeff) + 1
        num_big_subsequences = n_arcs % mixingCoeff
        num_total_big_subsequence_numbers = subsequence_length * num_big_subsequences

        i = 0
        j = 0
        # Arc a; _graph.first(a);
        # for (; a != INVALID; _graph.next(a)) {
        for a in range(n_arcs - 1, -1, -1):
            # _source[i] = _node_id(_graph.source(a));
            # _target[i] = _node_id(_graph.target(a));
            source[i] = n_nodes - (a // m) - 1
            target[i] = n_nodes - ((a % m) + n) - 1
            ## #_arc_id[a] = i;
            # if ((i += k) >= _arc_num) i = ++j;
            i += k
            if i >= n_arcs:
                j += 1
                i = j

    else:
        # dummy values
        subsequence_length = 0
        mixingCoeff = 0
        num_big_subsequences = 0
        num_total_big_subsequence_numbers = 0
        # Store the arcs in the original order
        i = 0
        # Arc a; _graph.first(a);
        # for (; a != INVALID; _graph.next(a), ++i) {
        for a in range(n_arcs - 1, -1, -1):
            # _source[i] = _node_id(_graph.source(a));
            # _target[i] = _node_id(_graph.target(a));
            source[i] = n_nodes - (a // m) - 1
            target[i] = n_nodes - ((a % m) + n) - 1
            ## #_arc_id[a] = i;

    # Reset parameters
    for i in range(n_nodes):  # (int i = 0; i != _node_num; ++i) {
        supply[i] = 0

    for i in range(n_arcs):  # (int i = 0; i != _arc_num; ++i) {
        cost[i] = 1

    # Default supply type is "GEQ"
    supply_type = "GEQ"

    node_arc_data = NodeArcData(cost, supply, flow, pi, source, target)
    spanning_tree = SpanningTree(
        parent, pred, thread, rev_thread, succ_num, last_succ, forward, state, root
    )
    graph = DiGraph(
        n_nodes,
        n_arcs,
        n,
        m,
        use_arc_mixing,
        num_total_big_subsequence_numbers,
        subsequence_length,
        num_big_subsequences,
        mixingCoeff,
    )

    return node_arc_data, spanning_tree, graph


# creates:
@numba.njit()
def initialize_graph_structures(graph, node_arc_data, spanning_tree):

    n_nodes = graph.n_nodes
    n_arcs = graph.n_arcs

    # unpack arrays
    cost = node_arc_data.cost
    supply = node_arc_data.supply
    flow = node_arc_data.flow
    pi = node_arc_data.pi
    source = node_arc_data.source
    target = node_arc_data.target

    parent = spanning_tree.parent
    pred = spanning_tree.pred
    thread = spanning_tree.thread
    rev_thread = spanning_tree.rev_thread
    succ_num = spanning_tree.succ_num
    last_succ = spanning_tree.last_succ
    forward = spanning_tree.forward
    state = spanning_tree.state

    if n_nodes == 0:
        return False, (0, 0, 0)

    # Check the sum of supply values
    net_supply = 0
    for i in range(n_nodes):  # (int i = 0; i != _node_num; ++i) {
        net_supply += supply[i]

    if np.fabs(net_supply) > NET_SUPPLY_ERROR_TOLERANCE:
        return False, (0, 0, 0)

    net_supply = 0  # !!!

    # Fix using doubles
    # Initialize artifical cost
    # Cost ART_COST;
    # if (std::numeric_limits<Cost>::is_exact) {
    #     ART_COST = std::numeric_limits<Cost>::max() / 2 + 1;
    # } else {
    ART_COST = 0.0
    for i in range(n_arcs):  # (int i = 0; i != _arc_num; ++i) {
        if cost[i] > ART_COST:
            ART_COST = cost[i]
    ART_COST = (ART_COST + 1) * n_nodes
    # }

    # Initialize arc maps
    for i in range(n_arcs):  # (int i = 0; i != _arc_num; ++i) {
        # _flow[i] = 0; # by default, the sparse matrix is empty
        state[i] = STATE_LOWER

    # Set data for the artificial root node
    root = n_nodes
    parent[root] = -1
    pred[root] = -1
    thread[root] = 0
    rev_thread[0] = root
    succ_num[root] = n_nodes + 1
    last_succ[root] = root - 1
    supply[root] = -net_supply
    pi[root] = 0

    # Add artificial arcs and initialize the spanning tree data structure
    if net_supply == 0:  # This was forced true by !!!
        # EQ supply constraints
        search_arc_num = n_arcs
        all_arc_num = n_arcs + n_nodes
        e = n_arcs
        for u in range(n_nodes):  # (int u = 0, e = _arc_num; u != _node_num;
            # ++u,
            # ++e) {
            parent[u] = root
            pred[u] = e
            thread[u] = u + 1
            rev_thread[u + 1] = u
            succ_num[u] = 1
            last_succ[u] = u
            state[e] = STATE_TREE
            if supply[u] >= 0:
                forward[u] = True
                pi[u] = 0
                source[e] = u
                target[e] = root
                flow[e] = supply[u]
                cost[e] = 0
            else:
                forward[u] = False
                pi[u] = ART_COST
                source[e] = root
                target[e] = u
                flow[e] = -supply[u]
                cost[e] = ART_COST
            e += 1

    elif net_supply > 0:
        # LEQ supply constraints
        search_arc_num = n_arcs + n_nodes
        f = n_arcs + n_nodes
        e = n_arcs
        for u in range(n_nodes):  # (int u = 0, e = _arc_num; u != _node_num;
            # ++u, ++e) {
            parent[u] = root
            thread[u] = u + 1
            rev_thread[u + 1] = u
            succ_num[u] = 1
            last_succ[u] = u
            if supply[u] >= 0:
                forward[u] = True
                pi[u] = 0
                pred[u] = e
                source[e] = u
                target[e] = root
                flow[e] = supply[u]
                cost[e] = 0
                state[e] = STATE_TREE
            else:
                forward[u] = False
                pi[u] = ART_COST
                pred[u] = f
                source[f] = root
                target[f] = u
                flow[f] = -supply[u]
                cost[f] = ART_COST
                state[f] = STATE_TREE
                source[e] = u
                target[e] = root
                # _flow[e] = 0;  //by default, the sparse matrix is empty
                cost[e] = 0
                state[e] = STATE_LOWER
                f += 1

            e += 1

        all_arc_num = f

    else:
        # GEQ supply constraints
        search_arc_num = n_arcs + n_nodes
        f = n_arcs + n_nodes
        e = n_arcs
        for u in range(n_nodes):  # (int u = 0, e = _arc_num; u != _node_num;
            # ++u, ++e) {
            parent[u] = root
            thread[u] = u + 1
            rev_thread[u + 1] = u
            succ_num[u] = 1
            last_succ[u] = u
            if supply[u] <= 0:
                forward[u] = False
                pi[u] = 0
                pred[u] = e
                source[e] = root
                target[e] = u
                flow[e] = -supply[u]
                cost[e] = 0
                state[e] = STATE_TREE
            else:
                forward[u] = True
                pi[u] = -ART_COST
                pred[u] = f
                source[f] = u
                target[f] = root
                flow[f] = supply[u]
                state[f] = STATE_TREE
                cost[f] = ART_COST
                source[e] = root
                target[e] = u
                # _flow[e] = 0; //by default, the sparse matrix is empty
                cost[e] = 0
                state[e] = STATE_LOWER
                f += 1

        all_arc_num = f

    return True, (net_supply, search_arc_num, all_arc_num)


@numba.njit()
def initialize_supply(left_node_supply, right_node_supply, graph, supply):
    # Node n; _graph.first(n);
    # for (; n != INVALIDNODE; _graph.next(n)) {
    for n in range(graph.n_nodes - 1, -1, -1):
        if n < graph.n:
            supply[graph.n_nodes - n - 1] = left_node_supply[n]
        else:
            supply[graph.n_nodes - n - 1] = right_node_supply[n - graph.n]


@numba.njit()
def set_cost(arc, cost_val, cost, graph):
    cost[arc_id(arc, graph)] = cost_val


@numba.njit()
def total_cost(flow, cost):
    c = 0.0
    for i in range(flow.shape[0]):  # (int i=0; i<_flow.size(); i++)
        c += flow[i] * cost[i]
    return c


@numba.njit()
def network_simplex_core(
    node_arc_data,
    spanning_tree,
    graph,
    sum_supply,
    search_arc_num,
    all_arc_num,
    supply_type,
    max_iter,
):
    # pivot_data = pivot(*this)
    pivot_block = PivotBlock(
        max(np.int32(np.sqrt(search_arc_num)), 10),
        np.zeros(1, dtype=np.int32),
        search_arc_num,
    )
    prevCost = -1.0
    solution_status = OPTIMAL

    # Perform heuristic initial pivots
    bounded, in_arc = construct_initial_pivots(
        sum_supply, graph, node_arc_data, spanning_tree
    )
    if not bounded:
        return UNBOUNDED

    iter_number = 0
    # pivot.setDantzig(true);
    # Execute the Network Simplex algorithm
    not_converged, in_arc = find_entering_arc(
        pivot_block, spanning_tree.state, node_arc_data, in_arc
    )
    while not_converged:
        iter_number += 1
        if max_iter > 0 and iter_number >= max_iter and max_iter > 0:
            print(
                "WARNING: RESULT MIGHT BE INACCURATE\nMax number of "
                "iteration reached. Sometimes iterations"
                " go on in "
                "cycle even though the solution has been reached, to check if it's the case here have a look at the minimal reduced cost. If it is very close to machine precision, you might actually have the correct solution, if not try setting the maximum number of iterations a bit higher\n"
            )
            solution_status = MAX_ITER_REACHED
            break

        # # if DEBUG_LVL>0
        # # if iter_number>MAX_DEBUG_ITER:
        # #     break
        # def _node_id(n):
        #     return graph.n_nodes - n - 1
        #
        # if iter_number % 100 == 0 or iter_number % 100 == 1:
        #     curCost = total_cost(node_arc_data.flow, node_arc_data.cost)
        #     sumFlow = 0
        #     if np.fabs(node_arc_data.pi[node_arc_data.source[in_arc]]) >= np.fabs(
        #         node_arc_data.pi[node_arc_data.target[in_arc]]
        #     ):
        #         a = np.fabs(node_arc_data.pi[node_arc_data.source[in_arc]])
        #     else:
        #         a = np.fabs(node_arc_data.pi[node_arc_data.target[in_arc]])
        #
        #     if a < np.fabs(node_arc_data.cost[in_arc]):
        #         a = np.fabs(node_arc_data.cost[in_arc])
        #
        #     for i in range(node_arc_data.flow.shape[0]):  # (int i=0; i<_flow.size();
        #         # i++) {
        #         sumFlow += spanning_tree.state[i] * node_arc_data.flow[i]
        #
        #     print(
        #         f"Sum of the flow {sumFlow}\n{iter_number} "
        #         f"iterations, current cost={curCost}\nReduced "
        #         f"cost="
        #         f"{spanning_tree.state[in_arc] * (node_arc_data.cost[in_arc] + node_arc_data.pi[node_arc_data.source[in_arc]] -node_arc_data.pi[node_arc_data.target[in_arc]])}\nPrecision = {-EPSILON*(a)}\n"
        #     )
        #     print(
        #         f"Arc in = ({_node_id(node_arc_data.source[in_arc])}, "
        #         f"{_node_id(node_arc_data.target[in_arc])})\n"
        #     )
        #     print(
        #         f"Supplies = ({node_arc_data.supply[node_arc_data.source[in_arc]]}, "
        #         f"{node_arc_data.supply[node_arc_data.target[in_arc]]} )\n"
        #     )
        #     print(node_arc_data.cost[in_arc])
        #     print(node_arc_data.pi[node_arc_data.source[in_arc]])
        #     print(node_arc_data.pi[node_arc_data.target[in_arc]])
        #     print(a)
        #     print(f"Number of non-zero flows: {np.sum(node_arc_data.flow != 0.0)}")
        # # endif

        join = find_join_node(
            node_arc_data.source,
            node_arc_data.target,
            spanning_tree.succ_num,
            spanning_tree.parent,
            in_arc,
        )
        change, (u_in, v_in, u_out, delta) = find_leaving_arc(
            join, in_arc, node_arc_data, spanning_tree
        )
        if delta >= MAX:
            return UNBOUNDED

        update_flow(change, join, delta, u_out, node_arc_data, spanning_tree, in_arc)

        if change:
            update_spanning_tree(
                spanning_tree, v_in, u_in, u_out, join, in_arc, node_arc_data.source
            )
            update_potential(
                u_in, v_in, node_arc_data.pi, node_arc_data.cost, spanning_tree
            )

        # # if DEBUG_LVL>0
        # else:
        #     print("No change")
        # # endif
        # # if DEBUG_LVL>1
        # # print(
        # #     f"Arc in = ({node_arc_data.source[in_arc]}, "
        # #     f"{node_arc_data.target[in_arc]})"
        # # )
        # # endif

        # #if DEBUG_LVL>0
        #                 double curCost=total_cost();
        #                 double sumFlow=0;
        #                 double a;
        #                 a= (fabs(_pi[_source[in_arc]])>=fabs(_pi[_target[in_arc]])) ? fabs(_pi[_source[in_arc]]) : fabs(_pi[_target[in_arc]]);
        #                 a=a>=fabs(_cost[in_arc])?a:fabs(_cost[in_arc]);
        #                 for (int i=0; i<_flow.size(); i++) {
        #                     sumFlow+=_state[i]*_flow[i];
        #                 }
        #
        #                 std::cout << "Sum of the flow " << std::setprecision(20) << sumFlow << "\n" << niter << " iterations, current cost=" << curCost << "\nReduced cost=" << _state[in_arc] * (_cost[in_arc] + _pi[_source[in_arc]] -_pi[_target[in_arc]]) << "\nPrecision = "<< -EPSILON*(a) << "\n";
        #
        #                 std::cout << "Arc in = (" << _node_id(_source[in_arc]) << ", " << _node_id(_target[in_arc]) <<")\n";
        #                 std::cout << "Supplies = (" << _supply[_source[in_arc]] << ", " << _supply[_target[in_arc]] << ")\n";

        # endif

        # #if DEBUG_LVL>1
        #             sumFlow=0;
        #             for (int i=0; i<_flow.size(); i++) {
        #                 sumFlow+=_state[i]*_flow[i];
        #                 if (_state[i]==STATE_TREE) {
        #                     std::cout << "Non zero value at (" << _node_num+1-_source[i] << ", " << _node_num+1-_target[i] << ")\n";
        #                 }
        #             }
        #             std::cout << "Sum of the flow " << sumFlow << "\n"<< niter <<" iterations, current cost=" << total_cost() << "\n";
        # #endif

        not_converged, in_arc = find_entering_arc(
            pivot_block, spanning_tree.state, node_arc_data, in_arc
        )

    flow = node_arc_data.flow
    pi = node_arc_data.pi

    # Check feasibility
    if solution_status == OPTIMAL:
        for e in range(pivot_block.search_arc_num, all_arc_num):
            if flow[e] != 0:
                if abs(flow[e]) > EPSILON:
                    return INFEASIBLE
                else:
                    flow[e] = 0

    # Shift potentials to meet the requirements of the GEQ/LEQ type
    # optimality conditions
    if sum_supply == 0:
        if supply_type == "GEQ":
            max_pot = -INFINITY
            for i in range(graph.n_nodes):
                if pi[i] > max_pot:
                    max_pot = pi[i]
            if max_pot > 0:
                for i in range(graph.n_nodes):
                    pi[i] -= max_pot

        else:
            min_pot = INFINITY
            for i in range(graph.n_nodes):
                if pi[i] < min_pot:
                    min_pot = pi[i]
            if min_pot < 0:
                for i in range(graph.n_nodes):
                    pi[i] -= min_pot

    return solution_status


@numba.njit()
def kantorovich_distance(x, y, cost, max_iter=1000000):
    node_arc_data, spanning_tree, graph = allocate_graph_structures(
        x.shape[0], y.shape[0]
    )
    initialize_supply(x, -y, graph, node_arc_data.supply)
    for i in range(cost.shape[0]):
        for j in range(cost.shape[1]):
            set_cost(i * cost.shape[1] + j, cost[i, j], node_arc_data.cost, graph)
    status, (sum_supply, search_arc_num, all_arc_num) = initialize_graph_structures(
        graph, node_arc_data, spanning_tree
    )
    network_simplex_core(node_arc_data, spanning_tree, graph, sum_supply,
                         search_arc_num, all_arc_num, "GEQ", max_iter)
    return total_cost(node_arc_data.flow, node_arc_data.cost)
