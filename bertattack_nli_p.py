# -*- coding: utf-8 -*-
# @Time    : 2020/6/10
# @Author  : Linyang Li
# @Email   : linyangli19@fudan.edu.cn
# @File    : attack.py


import warnings
import os
import torch
import torch.nn as nn
import json
import random
from torch.utils.data import DataLoader, SequentialSampler, TensorDataset
from transformers import BertConfig, BertTokenizer
from transformers import BertForSequenceClassification, BertForMaskedLM
from textattack.constraints.pre_transformation.min_word_length import MinWordLength
from textattack.transformations import WordSwapNeighboringCharacterSwap, \
    WordSwapRandomCharacterDeletion, WordSwapRandomCharacterInsertion, \
        WordSwapRandomCharacterSubstitution, WordSwapQWERTY
from textattack.augmentation import Augmenter
from textattack.transformations import CompositeTransformation
import copy
import argparse
import numpy as np
import time
from itertools import combinations, product
import ipdb
import unicodedata
from nltk.corpus import wordnet

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
warnings.simplefilter(action='ignore', category=FutureWarning)

filter_words = ['a', 'about', 'above', 'across', 'after', 'afterwards', 'again', 'against', 'ain', 'all', 'almost',
                'alone', 'along', 'already', 'also', 'although', 'am', 'among', 'amongst', 'an', 'and', 'another',
                'any', 'anyhow', 'anyone', 'anything', 'anyway', 'anywhere', 'are', 'aren', "aren't", 'around', 'as',
                'at', 'back', 'been', 'before', 'beforehand', 'behind', 'being', 'below', 'beside', 'besides',
                'between', 'beyond', 'both', 'but', 'by', 'can', 'cannot', 'could', 'couldn', "couldn't", 'd', 'didn',
                "didn't", 'doesn', "doesn't", 'don', "don't", 'down', 'due', 'during', 'either', 'else', 'elsewhere',
                'empty', 'enough', 'even', 'ever', 'everyone', 'everything', 'everywhere', 'except', 'first', 'for',
                'former', 'formerly', 'from', 'hadn', "hadn't", 'hasn', "hasn't", 'haven', "haven't", 'he', 'hence',
                'her', 'here', 'hereafter', 'hereby', 'herein', 'hereupon', 'hers', 'herself', 'him', 'himself', 'his',
                'how', 'however', 'hundred', 'i', 'if', 'in', 'indeed', 'into', 'is', 'isn', "isn't", 'it', "it's",
                'its', 'itself', 'just', 'latter', 'latterly', 'least', 'll', 'may', 'me', 'meanwhile', 'mightn',
                "mightn't", 'mine', 'more', 'moreover', 'most', 'mostly', 'must', 'mustn', "mustn't", 'my', 'myself',
                'namely', 'needn', "needn't", 'neither', 'never', 'nevertheless', 'next', 'no', 'nobody', 'none',
                'noone', 'nor', 'not', 'nothing', 'now', 'nowhere', 'o', 'of', 'off', 'on', 'once', 'one', 'only',
                'onto', 'or', 'other', 'others', 'otherwise', 'our', 'ours', 'ourselves', 'out', 'over', 'per',
                'please', 's', 'same', 'shan', "shan't", 'she', "she's", "should've", 'shouldn', "shouldn't", 'somehow',
                'something', 'sometime', 'somewhere', 'such', 't', 'than', 'that', "that'll", 'the', 'their', 'theirs',
                'them', 'themselves', 'then', 'thence', 'there', 'thereafter', 'thereby', 'therefore', 'therein',
                'thereupon', 'these', 'they', 'this', 'those', 'through', 'throughout', 'thru', 'thus', 'to', 'too',
                'toward', 'towards', 'under', 'unless', 'until', 'up', 'upon', 'used', 've', 'was', 'wasn', "wasn't",
                'we', 'were', 'weren', "weren't", 'what', 'whatever', 'when', 'whence', 'whenever', 'where',
                'whereafter', 'whereas', 'whereby', 'wherein', 'whereupon', 'wherever', 'whether', 'which', 'while',
                'whither', 'who', 'whoever', 'whole', 'whom', 'whose', 'why', 'with', 'within', 'without', 'won',
                "won't", 'would', 'wouldn', "wouldn't", 'y', 'yet', 'you', "you'd", "you'll", "you're", "you've",
                'your', 'yours', 'yourself', 'yourselves']
filter_words = set(filter_words)
f = None

class FixWordSwapQWERTY(WordSwapQWERTY):
    def _get_replacement_words(self, word):
        if len(word) <= 1:
            return []

        candidate_words = []

        start_idx = 1 if self.skip_first_char else 0
        end_idx = len(word) - (1 + self.skip_last_char)

        if start_idx >= end_idx:
            return []

        if self.random_one:
            i = random.randrange(start_idx, end_idx + 1)
            if len(self._get_adjacent(word[i])) == 0:
                candidate_word = (
                word[:i] + random.choice(list(self._keyboard_adjacency.keys())) + word[i + 1:]
                )
            else:
                candidate_word = (
                word[:i] + random.choice(self._get_adjacent(word[i])) + word[i + 1:]
                )
                candidate_words.append(candidate_word)
        else:
            for i in range(start_idx, end_idx + 1):
                for swap_key in self._get_adjacent(word[i]):
                    candidate_word = word[:i] + swap_key + word[i + 1 :]
                    candidate_words.append(candidate_word)

        return candidate_words

transformation = CompositeTransformation([
    WordSwapRandomCharacterDeletion(),
    WordSwapNeighboringCharacterSwap(),
    WordSwapRandomCharacterInsertion(),
    WordSwapRandomCharacterSubstitution(),
    FixWordSwapQWERTY(),
    ])
constraints = [MinWordLength(5)]

def filter_punc(word, prefix, use_bpe):
    global f
    if f is None:
        if use_bpe:
            f = open("./punc_log.txt", "w")
        else:
            f = open("./punc_log_wo_sub.txt", "w")
        print("use_bpe: {0}".format(use_bpe))
    
    punc_list = ".,?!@#$%^&*()_+=-[]{}:;`~<>\\\"\'"
    if prefix == 'sub\t':
        if word[:2] == "##":
            word = word[2:]
    # f.write(word + "\n")
    w = unicodedata.normalize('NFKC', word)
    for punc in punc_list:
        if punc in w:
            f.write(prefix + word + "\n")
            return True
    return False

def get_sim_embed(embed_path, sim_path):
    id2word = {}
    word2id = {}

    with open(embed_path, 'r', encoding='utf-8') as ifile:
        for line in ifile:
            word = line.split()[0]
            if word not in id2word:
                id2word[len(id2word)] = word
                word2id[word] = len(id2word) - 1

    cos_sim = np.load(sim_path)
    return cos_sim, word2id, id2word


def get_data_cls(data_path):
    label2id = {"entailment": 0, "neutral": 1, "contradiction": 2}
    lines = open(data_path, 'r', encoding='utf-8').readlines()[1:]
    features = []
    for i, line in enumerate(lines):
        split = line.strip('\n').split('\t')
        label = int(label2id[split[0]])
        h = split[1]
        p = split[2]

        features.append([h, p, label])
    return features


class Feature(object):
    def __init__(self, h, p, label):
        self.label = label
        self.h = h
        self.p = p
        self.final_adverse = p
        self.query = 0
        self.change = 0
        self.success = 0
        self.sim = 0.0
        self.changes = []
        # new
        self.label_adv = 0


def _tokenize(seq, tokenizer):
    seq = seq.replace('\n', '').lower()
    words = seq.split(' ')

    sub_words = []
    keys = []
    index = 0
    for word in words:
        sub = tokenizer.tokenize(word)
        sub_words += sub
        keys.append([index, index + len(sub)])
        index += len(sub)

    return words, sub_words, keys


def _get_masked(words):
    len_text = len(words)
    masked_words = []
    for i in range(len_text - 1):
        masked_words.append(words[0:i] + ['[UNK]'] + words[i + 1:])
    # list of words
    return masked_words


def get_important_scores(words, h, tgt_model, orig_prob, orig_label, orig_probs, tokenizer, batch_size, max_length):
    masked_words = _get_masked(words)
    texts = [' '.join(words) for words in masked_words]  # list of text of masked words
    all_input_ids = []
    all_masks = []
    all_segs = []
    for text in texts:
        inputs = tokenizer.encode_plus(h, text, add_special_tokens=True, max_length=max_length, )
        input_ids, token_type_ids = inputs["input_ids"], inputs["token_type_ids"]
        attention_mask = [1] * len(input_ids)
        padding_length = max_length - len(input_ids)
        input_ids = input_ids + (padding_length * [0])
        token_type_ids = token_type_ids + (padding_length * [0])
        attention_mask = attention_mask + (padding_length * [0])
        all_input_ids.append(input_ids)
        all_masks.append(attention_mask)
        all_segs.append(token_type_ids)
    seqs = torch.tensor(all_input_ids, dtype=torch.long)
    masks = torch.tensor(all_masks, dtype=torch.long)
    segs = torch.tensor(all_segs, dtype=torch.long)
    seqs = seqs.to('cuda')

    eval_data = TensorDataset(seqs)
    # Run prediction for full data
    eval_sampler = SequentialSampler(eval_data)
    eval_dataloader = DataLoader(eval_data, sampler=eval_sampler, batch_size=batch_size)
    leave_1_probs = []
    for batch in eval_dataloader:
        masked_input, = batch
        bs = masked_input.size(0)

        leave_1_prob_batch = tgt_model(masked_input)[0]  # B num-label
        leave_1_probs.append(leave_1_prob_batch)
    leave_1_probs = torch.cat(leave_1_probs, dim=0)  # words, num-label
    leave_1_probs = torch.softmax(leave_1_probs, -1)  #
    leave_1_probs_argmax = torch.argmax(leave_1_probs, dim=-1)
    import_scores = (orig_prob
                     - leave_1_probs[:, orig_label]
                     +
                     (leave_1_probs_argmax != orig_label).float()
                     * (leave_1_probs.max(dim=-1)[0] - torch.index_select(orig_probs, 0, leave_1_probs_argmax))
                     ).data.cpu().numpy()

    return import_scores


def get_substitues(tgt_word, substitutes, original, before_words, after_words, k, tokenizer, mlm_model, use_bpe, substitutes_score=None, threshold=3.0):
    # substitues L,k
    # from this matrix to recover a word
    words = []
    sub_len, k = substitutes.size()  # sub-len, k
    if sub_len == 1:
        for (i,j) in zip(substitutes[0], substitutes_score[0]):
            if threshold != 0 and j < threshold:
                break
            words.append(tokenizer._convert_id_to_token(int(i)))
    else:
        if use_bpe == 1:
            words = get_bpe_substitues(substitutes, original, before_words, after_words, k - num_typos, tokenizer, mlm_model)

    words = words[:k-num_typos]

    typos = set()
    if num_typos>0 and len(tgt_word)>=5:
        while len(typos) < num_typos:
            augmenter = Augmenter(transformation=transformation, constraints=constraints, pct_words_to_swap=0, transformations_per_example=num_typos)
            new_typos = augmenter.augment(tgt_word)
            if len(new_typos) < 2:
                break
            new_typos = set([t.lower() for t in new_typos if not wordnet.synsets(t)])
            typos |= new_typos

    typos = list(typos)
    typos = typos[:num_typos]

    return words+typos


def get_bpe_substitues(substitutes, original, before_words, after_words, arg_k, tokenizer, mlm_model):
    # substitutes L, k

    # substitutes = substitutes[0:12, 0:4] # maximum BPE candidates
    substitutes = substitutes[0:12, :]
    batch_size = 128

    # change num
    change_num = 3

    change_num = min(change_num, len(substitutes))

    # find all possible candidates 
    subst_wo_punc = []
    for i in range(substitutes.size(0)):
        temp = []
        cnt = 0
        for ids in substitutes[i]:
            if cnt == 4:
                break
            if not filter_punc(tokenizer._convert_id_to_token(int(ids)), 'sub\t', True):
                cnt += 1
                temp.append(int(ids))
        # no such subwords
        if cnt == 0:
            return []
        subst_wo_punc.append(temp)

    substitutes = subst_wo_punc

    all_substitutes = []

    combinator = combinations(list(range(len(substitutes))), change_num)
    combinator = list(combinator)
    for comb in combinator:
        c = 1
        lens = []
        for i in comb:
            c *= len(substitutes[i])
            lens.append(len(substitutes[i]))
        ids = []
        for num in range(c):
            temp = []
            n = num
            for i in lens:
                temp.append(n % i)
                n = n // i
            ids.append(temp)
        for i in range(len(ids)):
            # new_subs = [int(substitutes[comb[k]][j]) for k, j in enumerate(ids[i])]
            new_subs = []
            for k, j in enumerate(original):
                if k in comb:
                    new_subs.append(int(substitutes[k][ids[i][comb.index(k)]]))
                else:
                    new_subs.append(int(j))
            all_substitutes.append(new_subs)
    
    # ipdb.set_trace()
    all_phrases = []
    for i in range(len(all_substitutes)):
        all_phrases.append(before_words + all_substitutes[i] + after_words)

    # all substitutes  list of list of token-id (all candidates)
    c_loss = nn.CrossEntropyLoss(reduction='none')
    word_list = []
    # all_substitutes = all_substitutes[:24]
    all_phrases = torch.tensor(all_phrases) # [ N, L ]
    # all_substitutes = all_substitutes[:24].to('cuda')
    all_phrases = all_phrases.to('cuda')
    # print(substitutes.size(), all_substitutes.size())
    N, L = all_phrases.size()

    ppl = None
    cnt = 0
    while cnt < N:
        if ppl is None:
            word_predictions = mlm_model(all_phrases[:cnt+batch_size])[0]

            substitues_len = all_phrases[:cnt+batch_size].shape[0]
            size = batch_size if substitues_len == batch_size else substitues_len
            # print(all_substitutes[:cnt+batch_size].shape)
            ppl = c_loss(word_predictions.view(size * L, -1), all_phrases[:cnt+batch_size].view(-1))
        else:
            temp = mlm_model(all_phrases[cnt:cnt+batch_size])[0]

            substitues_len = all_phrases[cnt:cnt+batch_size].shape[0]
            size = batch_size if substitues_len == batch_size else substitues_len

            temp_ppl = c_loss(temp.view(size * L, -1), all_phrases[cnt:cnt+batch_size].view(-1))
            ppl = torch.cat([ppl, temp_ppl], dim=0)
        cnt += batch_size


    ppl = torch.exp(torch.mean(ppl.view(N, L), dim=-1)) # N  
    _, word_list = torch.sort(ppl)
    word_list = [all_substitutes[i] for i in word_list]
    final_words = []
    for word in word_list:
        tokens = [tokenizer._convert_id_to_token(int(i)) for i in word]
        text = tokenizer.convert_tokens_to_string(tokens)
        final_words.append(text)
    return final_words[:arg_k]


def attack(feature, tgt_model, mlm_model, tokenizer, k, batch_size, max_length=512, cos_mat=None, w2i={}, i2w={}, use_bpe=1, threshold_pred_score=0.3):
    # MLM-process
    words, sub_words, keys = _tokenize(feature.p, tokenizer)

    phrase_cnt = 2

    # original label
    inputs = tokenizer.encode_plus(feature.h, feature.p, add_special_tokens=True, max_length=max_length, )
    input_ids, token_type_ids = torch.tensor(inputs["input_ids"]), torch.tensor(inputs["token_type_ids"])
    attention_mask = torch.tensor([1] * len(input_ids))
    seq_len = input_ids.size(0)
    orig_probs = tgt_model(input_ids.unsqueeze(0).to('cuda'),
                           attention_mask.unsqueeze(0).to('cuda'),
                           token_type_ids.unsqueeze(0).to('cuda')
                           )[0].squeeze()
    orig_probs = torch.softmax(orig_probs, -1)
    orig_label = torch.argmax(orig_probs)
    current_prob = orig_probs.max()

    if orig_label != feature.label:
        feature.label_adv = -1
        feature.success = 3
        return feature

    sub_words = ['[CLS]'] + sub_words[:max_length - 2] + ['[SEP]']
    input_ids_ = torch.tensor([tokenizer.convert_tokens_to_ids(sub_words)])
    # get the output of the mlm model
    word_predictions = mlm_model(input_ids_.to('cuda'))[0].squeeze()  # seq-len(sub) vocab
    # select each k-outputs for each of the tokens
    word_pred_scores_all, word_predictions = torch.topk(word_predictions, k, -1)  # seq-len k

    # topk outputs (exclude [CLS])
    word_predictions = word_predictions[1:len(sub_words) + 1, :]
    # topk outputs' probability (exclude [CLS])
    word_pred_scores_all = word_pred_scores_all[1:len(sub_words) + 1, :]

    # sort the words with respect to the 'vulnerability'
    important_scores = get_important_scores(words, feature.h, tgt_model, current_prob, orig_label, orig_probs,
                                            tokenizer, batch_size, max_length)
    feature.query += int(len(words))
    list_of_index = sorted(enumerate(important_scores), key=lambda x: x[1], reverse=True)
    # print(list_of_index)
    final_words = copy.deepcopy(words)

    phrase_input_ids = input_ids_[0, 1:len(sub_words)+1].tolist()

    for top_index in list_of_index:
        if feature.change > int(0.4 * (len(words))):
            feature.label_adv = -1
            feature.success = 1  # exceed
            return feature

        tgt_word = words[top_index[0]]
        
        before_idx = 0 if top_index[0] - phrase_cnt < 0 else top_index[0] - phrase_cnt
        after_idx = len(words)-1 if top_index[0] + phrase_cnt > len(words) - 1 else top_index[0] + phrase_cnt

        before_words = phrase_input_ids[keys[before_idx][0]:keys[top_index[0]][0]]
        after_words = phrase_input_ids[keys[top_index[0]][1]:keys[after_idx][1]]

        if tgt_word in filter_words:
            continue
        # filter out the punctuation marks
        if filter_punc(tgt_word, "tgt_word\t", use_bpe):
            continue
        if keys[top_index[0]][0] > max_length - 2:
            continue

        substitutes = word_predictions[keys[top_index[0]][0]:keys[top_index[0]][1]]  # L, k
        word_pred_scores = word_pred_scores_all[keys[top_index[0]][0]:keys[top_index[0]][1]]

        orig_subword = (input_ids_[0, 1:len(sub_words)+1].tolist())[keys[top_index[0]][0]:keys[top_index[0]][1]]

        substitutes = get_substitues(tgt_word, substitutes, orig_subword, before_words, after_words, k, tokenizer, mlm_model, use_bpe, word_pred_scores, threshold_pred_score)


        most_gap = 0.0
        candidate = None

        for substitute_ in substitutes:
            substitute = substitute_

            if substitute == tgt_word:
                continue  # filter out original word
            if '##' in substitute:
                continue  # filter out sub-word

            if substitute in filter_words:
                continue
            # filter out the punctuation marks
            if filter_punc(substitute, "substitude\t", use_bpe):
                continue
            if substitute in w2i and tgt_word in w2i:
                if cos_mat[w2i[substitute]][w2i[tgt_word]] < 0.4:
                    continue
            temp_replace = final_words
            temp_replace[top_index[0]] = substitute
            temp_text = tokenizer.convert_tokens_to_string(temp_replace)
            inputs = tokenizer.encode_plus(feature.h, temp_text, add_special_tokens=True, max_length=max_length, )
            input_ids = torch.tensor(inputs["input_ids"]).unsqueeze(0).to('cuda')
            seq_len = input_ids.size(1)
            temp_prob = tgt_model(input_ids)[0].squeeze()
            feature.query += 1
            temp_prob = torch.softmax(temp_prob, -1)
            temp_label = torch.argmax(temp_prob)

            if temp_label != orig_label:
                feature.change += 1
                final_words[top_index[0]] = substitute
                feature.changes.append([keys[top_index[0]][0], substitute, tgt_word])
                feature.final_adverse = temp_text
                feature.success = 4
                feature.label_adv = temp_label.item()
                return feature
            else:

                label_prob = temp_prob[orig_label]
                gap = current_prob - label_prob
                if gap > most_gap:
                    most_gap = gap
                    candidate = substitute

        if most_gap > 0:
            feature.change += 1
            feature.changes.append([keys[top_index[0]][0], candidate, tgt_word])
            current_prob = current_prob - most_gap
            final_words[top_index[0]] = candidate

    feature.final_adverse = (tokenizer.convert_tokens_to_string(final_words))
    feature.label_adv = -1
    feature.success = 2
    return feature


def evaluate(features):
    do_use = 0
    use = None
    sim_thres = 0
    # evaluate with USE

    if do_use == 1:
        cache_path = ''
        import tensorflow as tf
        import tensorflow_hub as hub
    
        class USE(object):
            def __init__(self, cache_path):
                super(USE, self).__init__()

                self.embed = hub.Module(cache_path)
                config = tf.ConfigProto()
                config.gpu_options.allow_growth = True
                self.sess = tf.Session()
                self.build_graph()
                self.sess.run([tf.global_variables_initializer(), tf.tables_initializer()])

            def build_graph(self):
                self.sts_input1 = tf.placeholder(tf.string, shape=(None))
                self.sts_input2 = tf.placeholder(tf.string, shape=(None))

                sts_encode1 = tf.nn.l2_normalize(self.embed(self.sts_input1), axis=1)
                sts_encode2 = tf.nn.l2_normalize(self.embed(self.sts_input2), axis=1)
                self.cosine_similarities = tf.reduce_sum(tf.multiply(sts_encode1, sts_encode2), axis=1)
                clip_cosine_similarities = tf.clip_by_value(self.cosine_similarities, -1.0, 1.0)
                self.sim_scores = 1.0 - tf.acos(clip_cosine_similarities)

            def semantic_sim(self, sents1, sents2):
                sents1 = [s.lower() for s in sents1]
                sents2 = [s.lower() for s in sents2]
                scores = self.sess.run(
                    [self.sim_scores],
                    feed_dict={
                        self.sts_input1: sents1,
                        self.sts_input2: sents2,
                    })
                return scores[0]

            use = USE(cache_path)


    acc = 0
    origin_success = 0
    total = 0
    total_q = 0
    total_change = 0
    total_word = 0
    for feat in features:
        if feat.success > 2:

            if do_use == 1:
                sim = float(use.semantic_sim([feat.h], [feat.final_adverse]))
                if sim < sim_thres:
                    continue
            
            acc += 1
            total_q += feat.query
            total_change += feat.change
            total_word += len(feat.h.split(' '))

            if feat.success == 3:
                origin_success += 1

        total += 1

    suc = float(acc / total)

    query = float(total_q / acc)
    change_rate = float(total_change / total_word)

    origin_acc = 1 - origin_success / total
    after_atk = 1 - suc

    result_str = 'acc/aft-atk-acc {:.6f}/ {:.6f}, query-num {:.4f}, change-rate {:.4f}'.format(origin_acc, after_atk, query, change_rate)
    result_str += '\nacc: {:.6f}, total: {:.6f}, total_q: {:.6f}, total_change: {:.6f}, total_word: {:.6f}, origin_success: {:.6f}'.format(acc, total, total_q, total_change, total_word, origin_success)
    print(result_str)
    return result_str


def dump_features(features, output):
    outputs = []

    for feature in features:
        outputs.append({'label': feature.label,
                        'label_adv': feature.label_adv,
                        'success': feature.success,
                        'change': feature.change,
                        'num_word': len(feature.h.split(' ')),
                        'query': feature.query,
                        'changes': feature.changes,
                        'hypothesis': feature.h,
                        'premises': feature.p,
                        'adv': feature.final_adverse,
                        })
    output_json = output
    json.dump(outputs, open(output_json, 'w'), indent=2)

    print('finished dump')


def run_attack():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_path", type=str, help="./data/xxx")
    parser.add_argument("--mlm_path", type=str, help="xxx mlm")
    parser.add_argument("--tgt_path", type=str, help="xxx classifier")

    parser.add_argument("--output_dir", type=str, help="train file")
    parser.add_argument("--use_sim_mat", type=int, help='whether use cosine_similarity to filter out atonyms')
    parser.add_argument("--start", type=int, help="start step, for multi-thread process")
    parser.add_argument("--end", type=int, help="end step, for multi-thread process")
    parser.add_argument("--num_label", type=int, )
    parser.add_argument("--use_bpe", type=int, )
    parser.add_argument("--k", type=int, )
    parser.add_argument("--alpha", default = 0, type=int, )
    parser.add_argument("--threshold_pred_score", type=float, )


    args = parser.parse_args()
    data_path = str(args.data_path)
    mlm_path = str(args.mlm_path)
    tgt_path = str(args.tgt_path)
    output_dir = str(args.output_dir)
    num_label = args.num_label
    use_bpe = args.use_bpe
    k = args.k
    global num_typos
    num_typos = round((args.alpha/100)*(args.k))
    start = args.start
    end = args.end
    threshold_pred_score = args.threshold_pred_score

    print('start process')

    tokenizer_tgt = BertTokenizer.from_pretrained(tgt_path, do_lower_case=True)

    config_atk = BertConfig.from_pretrained(mlm_path)
    mlm_model = BertForMaskedLM.from_pretrained(mlm_path, config=config_atk)
    mlm_model.to('cuda')

    config_tgt = BertConfig.from_pretrained(tgt_path, num_labels=num_label)
    tgt_model = BertForSequenceClassification.from_pretrained(tgt_path, config=config_tgt)
    tgt_model.to('cuda')
    features = get_data_cls(data_path)
    
    if args.use_sim_mat == 1:
        cos_mat, w2i, i2w = get_sim_embed('data_defense/counter-fitted-vectors.txt', 'data_defense/cos_sim_counter_fitting.npy')
    else:        
        cos_mat, w2i, i2w = None, {}, {}

    features_output = []

    with torch.no_grad():
        for index, feature in enumerate(features[start:end]):
            h, p, label = feature
            feat = Feature(h, p, label)
            print('\r number {:d} '.format(index) + tgt_path, end='')
            feat = attack(feat, tgt_model, mlm_model, tokenizer_tgt, k, batch_size=32, max_length=512,
                          cos_mat=cos_mat, w2i=w2i, i2w=i2w, use_bpe=use_bpe,threshold_pred_score=threshold_pred_score)

            if feat.success > 2:
                print('success', end='')
            else:
                print('failed', end='')
            features_output.append(feat)

    result_str = evaluate(features_output)

    
    f = open(os.path.splitext(output_dir)[0] + "-" + str(args.alpha) + ".txt", "w")
    f.write(result_str)
    f.close()

    dump_features(features_output, os.path.splitext(output_dir)[0] + "-" + str(args.alpha).split('.')[0] + ".tsv")


if __name__ == '__main__':
    start = time.time()
    run_attack()
    print("Elapsed time: {:.4f}".format(time.time()-start))
    if f is not None:
        f.close()