"""A warned, preventable deposition when a regency has become entrenched."""
from .state import add_ledger


def succession_warning_text(state):
    """Keep the one-turn rescue deadline visible in the next morning's story."""
    warning = state.flags.get('succession_warning')
    if not warning or warning.get('regent') not in state.people:
        return ''
    regent = state.people[warning['regent']].name
    return (f'废立预警：{regent}正在谋议另立宗室旁支。本幕结束时，若你仍受制、'
            '正统不超过10，且对方的兵权或朝臣支持仍在，皇位将被夺走。'
            '请在本幕内争取复位支持、提高正统，或瓦解对方的兵权与朝臣支持。')


def advance_succession_pressure(state):
    from .intrigue import _allies
    from .engine import _new_face
    f = state.flags
    regent = f.get('power_holder_id')
    allies = _allies(state, regent) if regent in state.people else set()
    guard_holder = state.resources.get('guards', {}).get('holder_id')
    backing = guard_holder == regent or guard_holder in allies or 'minister' in allies
    eligible = (state.turn >= 6 and state.player_status == '受制'
                and state.current_ruler_id in state.player_lineage
                and regent not in state.player_lineage
                and regent in state.people and state.people[regent].alive
                and f.get('reputation', 50) <= 10 and backing)
    warning = f.get('succession_warning')
    if not eligible:
        if warning:
            add_ledger(state, '废立缓解', '复位或声望、兵权与朝臣支持的变化，使先前的废立动议暂时搁置。')
        f.pop('succession_warning', None)
        return
    if not warning or warning.get('regent') != regent:
        f['succession_warning'] = {'turn': state.turn, 'regent': regent}
        add_ledger(state, '废立预警', f"{state.people[regent].name}已有兵权或朝臣支持，开始议论另立宗室旁支。若下一幕结束时仍受制、正统不超过10且对方支持未散，皇位将被夺走；应争取复位支持或改善正统、瓦解其支持。")
        return
    if state.turn <= warning['turn']:
        return
    new_id = _new_face(state, 'heir')
    state.people[new_id].rank = '旁支新君'
    state.people[new_id].guardian_id = regent
    state.current_ruler_id = new_id
    state.player_status = '流亡'
    f['lineage_on_throne'] = False
    f.pop('succession_warning', None)
    add_ledger(state, '废立', f"废立预警后，{state.people[regent].name}的支持仍未瓦解。宗室旁支{state.people[new_id].name}被拥立，{state.people[state.player_id].name}失去皇位，玩家一脉流亡；实权仍在{state.people[regent].name}。")
