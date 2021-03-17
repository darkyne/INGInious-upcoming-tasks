#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#   @author 2021 Creupelandt Gregory starting from the auto-evaluation plugin from Ludovic Taffin
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU Affero General Public License for more details.
#
#   You should have received a copy of the GNU Affero General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.


""" A plugin that allow students to see their futur work in a single place for all their courses """
import json
import os
import copy
import flask

from math import ceil, floor
from collections import OrderedDict
from datetime import datetime, timedelta

from flask import send_from_directory
from inginious.frontend.pages.utils import INGIniousPage, INGIniousAuthPage

PATH_TO_PLUGIN = os.path.abspath(os.path.dirname(__file__))

def menu(template_helper):
    """ Displays the link to the board on the main page, if the plugin is activated """
    return template_helper.render("main_menu.html", template_folder=PATH_TO_PLUGIN + '/templates/')

class StaticMockPage(INGIniousPage):

    def GET(self, path):
        return send_from_directory(os.path.join(PATH_TO_PLUGIN, "static"), path)

    def POST(self, path):
        return self.GET(path)

class UpComingTasksBoard(INGIniousAuthPage):

    """called when reaching the page"""
    def GET_AUTH(self):
        time_planner = "unlimited" 
        return self.page(time_planner)

    """ called when modifying time planner"""
    def POST_AUTH(self): 
        user_input = flask.request.form
        time_planner = "unlimited"
        if "time_planner" in user_input:
            time_planner = user_input.get("time_planner")
        return self.page(time_planner)

    """Used to convert the time_planner options into int value"""
    def time_planner_converstion(self, string_time_planner):
        if (string_time_planner=="unlimited"):
            return 10000
        else:
            return int(string_time_planner)

    """General main method called for GET and POST"""
    def page (self, time_planner):
        username = self.user_manager.session_username()
        user_info = self.user_manager.get_user_info(username)
        all_courses = self.course_factory.get_all_courses()
        time_planner = self.time_planner_converstion(time_planner)

        """Get the courses id"""
        open_courses = {courseid: course for courseid, course in all_courses.items()
                        if self.user_manager.course_is_open_to_user(course, username, False) and
                        self.user_manager.course_is_user_registered(course, username)}
        open_courses = OrderedDict(sorted(iter(open_courses.items()), key=lambda x: x[1].get_name(self.user_manager.session_language())))

        courses = {self.course_factory.get_course(courseid): course for courseid, course in all_courses.items()
                   if self.user_manager.course_is_open_to_user(course, username, False) and
                   self.user_manager.course_is_user_registered(course, username)}

        """Get last submissions for left pannel"""
        last_submissions = self.submission_manager.get_user_last_submissions(5, {"courseid": {"$in": list(open_courses.keys())}})
        except_free_last_submissions = []
        for submission in last_submissions:
            try:
                submission["task"] = open_courses[submission['courseid']].get_task(submission['taskid'])
                except_free_last_submissions.append(submission)
            except:
                pass

        """Get the courses tasks, remove finished ones and courses that have no available unfinished tasks with upcoming deadline in range"""
        tasks_data = {}
        outdated_tasks=[]
        for course in courses:
            tasks = course.get_tasks()
            for task in tasks:
                the_task = course.get_task(task)
                if (the_task.get_accessible_time().is_open()==False or ( (the_task.get_accessible_time().get_soft_end_date()) > (datetime.now()+timedelta(days=time_planner)) )): 
                    outdated_tasks += [task]
            new_user_task_list = course.get_task_dispenser().get_user_task_list([username])[username]
            tasks_data.update({taskid: {"succeeded": False, "grade": 0.0} for taskid in new_user_task_list})

            user_tasks = self.database.user_tasks.find({"username": username, "courseid": course.get_id(), "taskid": {"$in": new_user_task_list}})
            for user_task in user_tasks:
                tasks_data[user_task["taskid"]]["succeeded"] = user_task["succeeded"]
                tasks_data[user_task["taskid"]]["grade"] = user_task["grade"]
                if ( (tasks_data[user_task["taskid"]]["grade"] == 100.0)): 
                    tasks_data.pop(user_task["taskid"])
            "Remove outdated tasks and courses with no unfinished available tasks with deadline"""
            for outdated_task in outdated_tasks:
                if outdated_task in tasks_data:
                    tasks_data.pop(outdated_task)
            if (not any(task in tasks for task in tasks_data)):
                open_courses.pop(course.get_id())

        my_render=Render_Ordered(username)
        time_planner = ["7", "14", "30", "unlimited"]
        tasks_data_keys = list(tasks_data.keys())

        """Sort the courses based on the most urgent task for each course"""
        open_courses = OrderedDict( sorted(iter(open_courses.items()), key=lambda x: (sort_by_deadline(x[1], tasks_data_keys)[0]).get_accessible_time().get_soft_end_date() ))

        return self.template_helper.render("coming_tasks.html",
                                           template_folder=PATH_TO_PLUGIN + "/templates/",
                                           open_courses=open_courses,
                                           tasks_data=tasks_data,
                                           tasks_list = list(tasks_data.keys()),
                                           my_render=my_render,
                                           time_planner=time_planner,
                                           submissions=except_free_last_submissions)


"""Class representing a render which is sent to the html file where it is recursively called with jinja"""
class Render_Ordered:

    def __init__(self, username):
        self.username = username

    """This method is encapsuled in the render object to allow calling easily from jinja"""
    def order(self, course, task_list):
        return sort_by_deadline(course, task_list)


    """Used to render the task list filtered on deadlines
    course is a course object
    tasks_data is a dictionnary of data about tasks (including grade)
    tasks_list is a list of urgent tasksid
    the Render_Ordered object is sent to allow calling its order method"""
    def render_upcoming_list(self, template_helper, course, tasks_data, tasks_list):
        return template_helper.render("upcoming.html", template_folder=PATH_TO_PLUGIN + '/templates/', course=course,
                                      tasks_data=tasks_data, tasks_list=tasks_list, render=self)



"""Given a course (object) and a list of user urgent tasksid,
returns the list of urgent tasks (objects) for that course ordered based on deadline"""
def sort_by_deadline(course, user_urgent_task_list):
    course_tasks = course.get_tasks()
    course_user_urgent_task_list = list(set(course_tasks).intersection(user_urgent_task_list))
    ordered_tasks = sorted(course_user_urgent_task_list, key=lambda x: course.get_task(x).get_accessible_time().get_soft_end_date())
    ordered_tasks = map(course.get_task, ordered_tasks)
    return list(ordered_tasks)
  
def init(plugin_manager, _, _2, config):
    """ Init the plugin """
    plugin_manager.add_page('/coming_tasks', UpComingTasksBoard.as_view("upcomingtasksboardpage"))
    plugin_manager.add_page('/plugins/coming_tasks/static/<path:path>', StaticMockPage.as_view("upcomingtasksstaticmockpage"))
    plugin_manager.add_hook('main_menu', menu)
