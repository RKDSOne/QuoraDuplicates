from __future__ import absolute_import
from __future__ import division

import tensorflow as tf
import numpy as np
import os

from model import Model

class SiameseModel(Model):
    """
    Implements a recursive neural network with an embedding layer and
    single hidden layer.
    """
    def add_placeholders(self):
        self.input1_placeholder = tf.placeholder(tf.int32, (None, self.max_length))
        self.input2_placeholder = tf.placeholder(tf.int32, (None, self.max_length))
        self.labels_placeholder = tf.placeholder(tf.float32, (None, 2))
        self.seqlen1_placeholder = tf.placeholder(tf.int32, (None,))
        self.seqlen2_placeholder = tf.placeholder(tf.int32, (None,))
        self.dropout_placeholder = tf.placeholder(tf.float32, [])

    def create_feed_dict(self, inputs1_batch, inputs2_batch, seqlen1_batch, seqlen2_batch, labels_batch=None, dropout=1):
        """Creates the feed_dict.

        Note: The signature of this function must match the return value of preprocess_sequence_data.

        Returns:
            feed_dict: The feed dictionary mapping from placeholders to values.
        """
        feed_dict = {
            self.input1_placeholder: inputs1_batch,
            self.input2_placeholder: inputs2_batch,
            self.seqlen1_placeholder: seqlen1_batch,
            self.seqlen2_placeholder: seqlen2_batch,
            self.dropout_placeholder: dropout
        }
        if labels_batch is not None:
            sp_labels = [(1, 0) if l == 0 else (0, 1) for l in labels_batch]
            sp_labels = np.array(sp_labels, dtype=np.float32)
            feed_dict.update({self.labels_placeholder: sp_labels})
        return feed_dict

    def add_prediction_op(self):
        x1 = self.add_embedding(1)
        x2 = self.add_embedding(2)
        dropout_rate = self.dropout_placeholder

        BasicLSTMCell = tf.contrib.rnn.BasicLSTMCell if hasattr(tf.contrib.rnn, 'BasicLSTMCell') else tf.nn.rnn_cell.BasicLSTMCell
        LSTMStateTuple = tf.contrib.rnn.LSTMStateTuple if hasattr(tf.contrib.rnn, 'LSTMStateTuple') else tf.nn.rnn_cell.LSTMStateTuple
        DropoutWrapper = tf.contrib.rnn.DropoutWrapper if hasattr(tf.contrib.rnn, 'DropoutWrapper') else tf.nn.rnn_cell.DropoutWrapper

        if self.config.cell == "lstm":
            cell = BasicLSTMCell(self.config.hidden_size)
            cell = DropoutWrapper(cell, dropout_rate)
        else:
            raise ValueError("Unsuppported cell type: " + self.config.cell)

        xavier_init = tf.contrib.layers.xavier_initializer()

        
        m = self.config.second_hidden_size
        with tf.variable_scope("HiddenLayerVars"):
            b1 = tf.get_variable("b1", initializer=xavier_init, shape=[1, m])
            b2 = tf.get_variable("b2", initializer=xavier_init, shape=[1, 2])
            #W1 = tf.get_variable("W1", initializer=xavier_init, shape=[3*self.config.hidden_size+1, m])
            W1 = tf.get_variable("W1",initializer=xavier_init, shape=[3*(self.config.hidden_size+1)+1 + self.config.batch_size, m])
            W2 = tf.get_variable("W2", initializer=xavier_init, shape=[m, 2])
            tf.get_variable_scope().reuse_variables()

        # Initialize state as vector of zeros.
        batch_size = tf.shape(x1)[0]
        with tf.variable_scope("hCLayer"):
            h1 = tf.get_variable("h1", initializer=xavier_init, shape=(self.config.batch_size, self.config.hidden_size))
            c1 = tf.get_variable("c1",shape=(self.config.batch_size, self.config.hidden_size),  initializer=xavier_init)
            h2 =tf.get_variable("h2", shape=(self.config.batch_size, self.config.hidden_size),
               initializer=tf.contrib.layers.xavier_initializer())
            c2 = tf.get_variable("c2",shape=(self.config.batch_size, self.config.hidden_size),  initializer=xavier_init)
            W_h = tf.get_variable("Wh",initializer=xavier_init, shape=(self.config.hidden_size + 1,self.config.hidden_size + 1))
            tf.get_variable_scope().reuse_variables()
        # h1 = tf.zeros([batch_size, self.config.hidden_size], dtype=tf.float32)
        # c1 = tf.zeros([batch_size, self.config.hidden_size], dtype=tf.float32)
        # h2 = tf.zeros([batch_size, self.config.hidden_size], dtype=tf.float32)
        # c2 = tf.zeros([batch_size, self.config.hidden_size], dtype=tf.float32)
        with tf.variable_scope("LSTM"):
            _, (c1, h1) = tf.nn.dynamic_rnn(cell, x1, initial_state=LSTMStateTuple(c1, h1), sequence_length=self.seqlen1_placeholder)
            #h1_drop = tf.nn.dropout(h1, keep_prob=dropout_rate)
            tf.get_variable_scope().reuse_variables()
            _, (c2, h2) = tf.nn.dynamic_rnn(cell, x2, initial_state=LSTMStateTuple(c2, h2), sequence_length=self.seqlen2_placeholder)
            #h2_drop = tf.nn.dropout(h2, keep_prob=dropout_rate)

        # add sentence length
        sent_len1 = tf.cast(tf.reshape(self.seqlen1_placeholder, [batch_size,1]), tf.float32) / float(self.config.max_length)
        sent_len2 = tf.cast(tf.reshape(self.seqlen2_placeholder, [batch_size,1]), tf.float32) / float(self.config.max_length)
        if int(tf.__version__.split('.')[0]) >= 1: # TensorFlow 1.0 or greater
            h1 = tf.concat([h1, sent_len1], 1) # hidden_size+1
            h2 = tf.concat([h2, sent_len2], 1) # hidden_size+1
        else:
            h1 = tf.concat(1, [h1, sent_len1]) # hidden_size+1
            h2 = tf.concat(1, [h2, sent_len2]) # hidden_size+1
        # end of adding sentence length

        h_sub = tf.subtract(h1, h2)
        sqdiff_12 = tf.square(h_sub)
        sqdist_12 = tf.reduce_sum(sqdiff_12, 1)
        h_dist = tf.reshape(sqdist_12, [batch_size,1])
        h_mul = tf.multiply(h1, h2)
        h1_MUL_W_h = tf.matmul(h1, W_h) # [batch_size(h+1)]x[(h+1)x(h+1)] = [batch_size(h+1)]
        h_interaction = tf.matmul(h1_MUL_W_h, tf.transpose(h2)) # [batch_size(h+1)]x[(h+1)xbatch_size]
        if int(tf.__version__.split('.')[0]) >= 1: # TensorFlow 1.0 or greater
            h_combined = tf.concat([h1, h2, h_dist, h_mul, h_interaction], 1) # 3*hidden_size+1 + batch_size
        else:
            h_combined = tf.concat(1, [h1, h2, h_dist, h_mul, h_interaction]) # 3*hidden_size+1 + batch_size
        #h_combined_drop = tf.nn.dropout(h_combined, keep_prob=dropout_rate)

        e1 = tf.matmul(h_combined, W1) + b1 # [batch_size, m]
        e1_relu = tf.nn.relu(e1)
        e1_drop = tf.nn.dropout(e1_relu, keep_prob=dropout_rate)
        preds = tf.matmul(e1_drop, W2) + b2

        return preds

    def add_exact_prediction_op(self, preds):
        pos_thres = tf.constant(0.5, dtype=tf.float32, shape=(1,))
        return tf.greater(tf.sigmoid(preds[:, 1]), pos_thres)


    def add_loss_op(self, preds):
        """Adds Ops for the loss function to the computational graph.

        Compute averaged cross entropy loss for the predictions.
        Importantly, you must ignore the loss for any masked tokens.

        Args:
            pred: A tensor of shape (batch_size, max_length, n_classes) containing the output of the neural
                  network before the softmax layer.
        Returns:
            loss: A 0-d tensor (scalar)
        """
        
        m = self.config.second_hidden_size
        loss = tf.reduce_mean(tf.nn.weighted_cross_entropy_with_logits(targets=self.labels_placeholder, logits=preds, pos_weight=1.675))       
        with tf.variable_scope("HiddenLayerVars", reuse=True):
            W1 = tf.get_variable("W1")
            W2 = tf.get_variable("W2")
        loss = loss + self.config.beta*tf.nn.l2_loss(W1)+ self.config.beta*tf.nn.l2_loss(W2)

        return loss

    def add_training_op(self, loss):
        global_step = tf.Variable(0, name='global_step', trainable=False)
        starter_learning_rate = self.config.lr
        learning_rate = tf.train.exponential_decay(starter_learning_rate, global_step,
                                                   85015, self.config.lr_decay_rate, staircase=True)
        optimizer = tf.train.AdamOptimizer(learning_rate)
        train_op = optimizer.minimize(loss, global_step=global_step)
        return train_op

    def preprocess_sequence_data(self, examples):
        return pad_sequences(examples, self.max_length)

def pad_sequences(data, max_length, n_features=1):
    ret = []

    # Use this zero vector when padding sequences.
    zero_vector = [0] * n_features

    for sentence1, sentence2, label in data:
        feat_sent1 = zero_vector * max_length
        feat_sent2 = zero_vector * max_length
        for i, word in enumerate(sentence1):
            if i >= max_length:
                break
            feat_sent1[i] = word

        for i, word in enumerate(sentence2):
            if i >= max_length:
                break
            feat_sent2[i] = word
        seqlen1 = min(len(sentence1), max_length)
        seqlen2 = min(len(sentence2), max_length)
        ret.append((feat_sent1, feat_sent2, seqlen1, seqlen2, label))
    return ret
