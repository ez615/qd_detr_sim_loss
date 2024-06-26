import torch


def span_xx_to_cxw(xx_spans):
    """
    Args:
        xx_spans: tensor, (#windows, 2) or (..., 2), each row is a window of format (st, ed)

    Returns:
        cxw_spans: tensor, (#windows, 2), each row is a window of format (center=(st+ed)/2, width=(ed-st))
    >>> spans = torch.Tensor([[0, 1], [0.2, 0.4]])
    >>> span_xx_to_cxw(spans)
    tensor([[0.5000, 1.0000],
        [0.3000, 0.2000]])
    >>> spans = torch.Tensor([[[0, 1], [0.2, 0.4]]])
    >>> span_xx_to_cxw(spans)
    tensor([[[0.5000, 1.0000],
         [0.3000, 0.2000]]])
    """
    center = xx_spans.sum(-1) * 0.5
    width = xx_spans[..., 1] - xx_spans[..., 0]
    return torch.stack([center, width], dim=-1)


def span_cxw_to_xx(cxw_spans):
    """
    Args:
        cxw_spans: tensor, (#windows, 2) or (..., 2), the last dim is a row denoting a window of format (center, width)

    >>> spans = torch.Tensor([[0.5000, 1.0000], [0.3000, 0.2000]])
    >>> span_cxw_to_xx(spans)
    tensor([[0.0000, 1.0000],
        [0.2000, 0.4000]])
    >>> spans = torch.Tensor([[[0.5000, 1.0000], [0.3000, 0.2000]]])
    >>> span_cxw_to_xx(spans)
    tensor([[[0.0000, 1.0000],
        [0.2000, 0.4000]]])
    """
    x1 = cxw_spans[..., 0] - 0.5 * cxw_spans[..., 1]
    x2 = cxw_spans[..., 0] + 0.5 * cxw_spans[..., 1]
    return torch.stack([x1, x2], dim=-1)


def temporal_iou(spans1, spans2):
    """
    Args:
        spans1: (N, 2) torch.Tensor, each row defines a span [st, ed]
        spans2: (M, 2) torch.Tensor, ...

    Returns:
        iou: (N, M) torch.Tensor
        union: (N, M) torch.Tensor
    >>> test_spans1 = torch.Tensor([[0, 0.2], [0.5, 1.0]])
    >>> test_spans2 = torch.Tensor([[0, 0.3], [0., 1.0]])
    >>> temporal_iou(test_spans1, test_spans2)
    (tensor([[0.6667, 0.2000],
         [0.0000, 0.5000]]),
     tensor([[0.3000, 1.0000],
             [0.8000, 1.0000]]))
    """
    areas1 = spans1[:, 1] - spans1[:, 0]  # (N, )
    areas2 = spans2[:, 1] - spans2[:, 0]  # (M, )

    left = torch.max(spans1[:, None, 0], spans2[:, 0])  # (N, M)
    right = torch.min(spans1[:, None, 1], spans2[:, 1])  # (N, M)

    inter = (right - left).clamp(min=0)  # (N, M)
    union = areas1[:, None] + areas2 - inter  # (N, M)

    iou = inter / union
    return iou, union


def temporal_intersection_over_pred(gt_spans, pred_spans):
    """ intersection over the second input spans
    Args:
        gt_spans: (N, 2),
        pred_spans: (M, 2)

    Returns:

    """
    left = torch.max(gt_spans[:, None, 0], pred_spans[:, 0])
    right = torch.min(gt_spans[:, None, 1], pred_spans[:, 1])

    inter = (right - left).clamp(min=0)  # (N, M)
    inter_over_pred = inter / (pred_spans[:, 1] - pred_spans[:, 0])
    return inter_over_pred


def generalized_temporal_iou(spans1, spans2):
    """
    Generalized IoU from https://giou.stanford.edu/
    Also reference to DETR implementation of generalized_box_iou
    https://github.com/facebookresearch/detr/blob/master/util/box_ops.py#L40

    Args:
        spans1: (N, 2) torch.Tensor, each row defines a span in xx format [st, ed]
        spans2: (M, 2) torch.Tensor, ...

    Returns:
        giou: (N, M) torch.Tensor

    >>> test_spans1 = torch.Tensor([[0, 0.2], [0.5, 1.0]])
    >>> test_spans2 = torch.Tensor([[0, 0.3], [0., 1.0]])
    >>> generalized_temporal_iou(test_spans1, test_spans2)
    tensor([[ 0.6667,  0.2000],
        [-0.2000,  0.5000]])
    """
    spans1 = spans1.float()
    spans2 = spans2.float()
    assert (spans1[:, 1] >= spans1[:, 0]).all()
    assert (spans2[:, 1] >= spans2[:, 0]).all()
    iou, union = temporal_iou(spans1, spans2)

    left = torch.min(spans1[:, None, 0], spans2[:, 0])  # (N, M)
    right = torch.max(spans1[:, None, 1], spans2[:, 1])  # (N, M)
    enclosing_area = (right - left).clamp(min=0)  # (N, M)

    return iou - (enclosing_area - union) / enclosing_area


### When using new loss with pretrain dataset
### durations of pretrian dataset are various (120 ~ 150)
def S_Diff(iou, spans1, spans2, logits, idx):
    # spans1 = spans1.float()
    # spans2 = spans2.float()

    # iou, union = temporal_iou(spans1, spans2)

    # # [spans1, spans2] == [start clip number, end clip number]
    # spans1 = torch.round(spans1 * 75)
    # spans2 = torch.round(spans2 * 75)
    
    # assert (spans1[:, 1] >= spans1[:, 0]).all()
    # assert (spans2[:, 1] >= spans2[:, 0]).all()

    bsz, vid_len = logits.shape

    src_spans = [[] for i in range(bsz)]
    tgt_spans = [[] for i in range(bsz)]

    for b, i in enumerate(idx):
        src_spans[i].append(spans1[b].int().detach().cpu())
        tgt_spans[i].append(spans2[b].int().detach().cpu())

    sim_diffs = []

    for i in range(bsz):
        logit = logits[i]

        for j in range(len(src_spans[i])):
            
            st, end = src_spans[i][j]
            st, end = min(max(st, 0), vid_len - 1), min(end, vid_len - 1)  # sometimes st is negative or end is larger than max_clip_len
            src_sim = logit[st:end + 1].mean()
            if torch.isnan(src_sim):
                print(f'\nsrc: {src_sim},vid_len: {vid_len} \nbefore {src_spans[i][j]}\nafter [{st}, {end}]')

            st, end = tgt_spans[i][j]
            st, end = min(st, vid_len - 1), min(end, vid_len - 1)   # somtimes there are over-ranged gt window in pretrain dataset
            tgt_sim = logit[st:end + 1].mean()
            if torch.isnan(tgt_sim):
                print(f'\ntgt: {tgt_sim}, \nbefore {tgt_spans[i][j]}\nafter [{st}, {end}]')

            sim_diff = torch.abs(src_sim - tgt_sim)  # L1 distance
            sim_diffs.append(sim_diff) 

    sim_diffs = torch.stack(sim_diffs, dim=0)

    # iou = torch.diag(iou)
    # new_iou = iou - (1 - iou) * sim_diffs

    sim_diff_term = (1 - iou) * sim_diffs

    return sim_diff_term


def S_GT_P(iou, spans1, spans2, v2v_sims, idx):  # S(Gt-P)
    bsz, vid_len, _ = v2v_sims.shape

    src_spans = [[] for i in range(bsz)]  # prediction
    tgt_spans = [[] for i in range(bsz)]

    for b, i in enumerate(idx):
        src_spans[i].append(spans1[b].int().detach().cpu())
        tgt_spans[i].append(spans2[b].int().detach().cpu())

    i2i_sims = []
    for i in range(bsz):
        v2v_sim = v2v_sims[i]

        for j in range(len(src_spans[i])):
            
            st, end = src_spans[i][j]
            st, end = min(max(st, 0), vid_len - 1), min(end, vid_len - 1)  # sometime st is negative value
            # src_feat = vid_feat[st:end + 1].mean(dim=0)
            i2i_sim = v2v_sim[st: end + 1, :]

            st, end = tgt_spans[i][j]
            st, end = min(st, vid_len - 1), min(end, vid_len - 1)
            # tgt_feat = vid_feat[st:end + 1].mean(dim=0)
            i2i_sim = i2i_sim[:, st: end + 1]

            i2i_sim = i2i_sim.flatten().mean()

            # i2i_sim = src_feat @ tgt_feat.t()
            # i2i_sims.append(i2i_sim)
            i2i_sims.append(i2i_sim)

    i2i_sims = torch.stack(i2i_sims, dim=0)

    # iou = torch.diag(iou)
    
    # new_iou = iou - (1 - iou) * (1 - i2i_sims)
    sim_gt_p_term = (1 - iou) * (1 - i2i_sims)

    return sim_gt_p_term

def S_GT_P_2(iou, spans1, spans2, v2v_sims, idx):  # S(Gt-P) ver2: pred-gt
    bsz, vid_len, _ = v2v_sims.shape

    src_spans = [[] for i in range(bsz)]  #pred
    tgt_spans = [[] for i in range(bsz)]  #gt

    for b, i in enumerate(idx):
        src_spans[i].append(spans1[b].int().detach().cpu())
        tgt_spans[i].append(spans2[b].int().detach().cpu())

    i2i_sims = []
    for i in range(bsz):
        v2v_sim = v2v_sims[i]

        for j in range(len(src_spans[i])):
            
            st, end = src_spans[i][j]
            st, end = min(max(st, 0), vid_len - 1), min(end, vid_len - 1)  # sometime st is negative value
            i2i_sim = v2v_sim[st: end + 1, :]

            st, end = tgt_spans[i][j]
            st, end = min(st, vid_len - 1), min(end, vid_len - 1)
            i2i_sim = i2i_sim[:, st: end + 1]

            i2i_sim = i2i_sim.max(dim=1)[0].mean()

            i2i_sims.append(i2i_sim)

    i2i_sims = torch.stack(i2i_sims, dim=0)

    sim_gt_p_term = (1 - iou) * (1 - i2i_sims)

    return sim_gt_p_term

def S_GT_P_3(iou, spans1, spans2, v2v_sims, idx):  # S(Gt-P) ver3: gt-pred
    bsz, vid_len, _ = v2v_sims.shape

    src_spans = [[] for i in range(bsz)]  #pred
    tgt_spans = [[] for i in range(bsz)]  #gt

    for b, i in enumerate(idx):
        src_spans[i].append(spans1[b].int().detach().cpu())
        tgt_spans[i].append(spans2[b].int().detach().cpu())

    i2i_sims = []
    for i in range(bsz):
        v2v_sim = v2v_sims[i]

        for j in range(len(src_spans[i])):
            st, end = tgt_spans[i][j]
            st, end = min(st, vid_len - 1), min(end, vid_len - 1)
            i2i_sim = v2v_sim[st: end + 1, :]

            st, end = src_spans[i][j]
            st, end = min(max(st, 0), vid_len - 1), min(end, vid_len - 1)  # sometime st is negative value
            i2i_sim = i2i_sim[:, st: end + 1]

            i2i_sim = i2i_sim.max(dim=1)[0].mean()

            i2i_sims.append(i2i_sim)

    i2i_sims = torch.stack(i2i_sims, dim=0)

    sim_gt_p_term = (1 - iou) * (1 - i2i_sims)

    return sim_gt_p_term

def S_Q_P(iou, spans, logits, idx):  # S(Q-P)
    # spans1 = spans1.float()
    # spans2 = spans2.float()

    # iou, union = temporal_iou(spans1, spans2)

    # # [spans1, spans2] == [start clip number, end clip number]
    # spans = torch.round(spans2 * 75)
    
    # assert (spans[:, 1] >= spans[:, 0]).all()

    bsz, vid_len = logits.shape

    src_spans = [[] for i in range(bsz)]

    for b, i in enumerate(idx):
        src_spans[i].append(spans[b].int().detach().cpu())

    t2i_sims = []
    # src_sims = []
    for i in range(bsz):
        logit = logits[i]

        for j in range(len(src_spans[i])):
        
            st, end = src_spans[i][j]
            st, end = min(max(st, 0), vid_len - 1), min(end, vid_len - 1)  # sometime st is negative value
            src_sim = logit[st:end + 1].mean()

            t2i_sims.append(src_sim)

    t2i_sims = torch.stack(t2i_sims, dim=0)

    # iou = torch.diag(iou)
    # new_iou = iou - (1 - iou) * (1 - t2i_sims)

    sim_p_q_term = (1 - iou) * (1 - t2i_sims)

    return sim_p_q_term


def distance_term(spans1, spans2):
    left = torch.min(spans1[:, None, 0], spans2[:, 0])  # (N, M)
    right = torch.max(spans1[:, None, 1], spans2[:, 1])  # (N, M)
    
    enclosing_area = torch.diag((right - left).clamp(min=0))  # (N, M)

    center1 = torch.diag((spans1[:, None, 0] + spans1[:, None, 1]) / 2)
    center2 = (spans2[:, 0] + spans2[:, 1]) / 2
    center_dist = torch.abs(center2 - center1)

    distance = center_dist / (enclosing_area ** 2)

    return distance

def new_loss(iou_loss_types, spans1, spans2, sims, idx):
    spans1 = spans1.float()
    spans2 = spans2.float()

    iou, _ = temporal_iou(spans1, spans2)
    iou = torch.diag(iou)

    if not 2 in iou_loss_types:
        sims = sims[0]
        vid_clip_len = sims.shape[1]

    else:
        if len(iou_loss_types) > 1:
            sims, vid_feat = sims
        else:
            vid_feat = sims[1]

        vid_clip_len = vid_feat.shape[1]

        
    # if (spans2[:, 1] * vid_clip_len >= vid_clip_len).any() or (spans2[:, 0] * vid_clip_len >= vid_clip_len).any():
    #     print(f'len: {vid_clip_len}')
    #     print(spans2 * vid_clip_len)

    # [spans1, spans2] == [start clip number, end clip number]
    spans1 = torch.round(spans1 * vid_clip_len)
    spans2 = torch.round(spans2 * vid_clip_len)
    
    assert (spans1[:, 1] >= spans1[:, 0]).all()
    assert (spans2[:, 1] >= spans2[:, 0]).all()

    new_loss = 1 - iou

    if 1 in iou_loss_types:
        new_loss += S_Diff(iou, spans1, spans2, sims, idx)

    if 2 in iou_loss_types:
        new_loss += S_GT_P(iou,spans1, spans2, vid_feat, idx) 
    
    if 3 in iou_loss_types:
        new_loss += S_Q_P(iou, spans1, sims, idx)


    return new_loss, iou