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

#   Auto-evaluation plugin for INGInious

""" A plugin that allow students to see their futur work in a single place for all their courses """
import json
import os
import copy
import flask

from math import ceil, floor
from collections import OrderedDict
from datetime import datetime
from datetime import timedelta 

from flask import send_from_directory
from inginious.frontend.pages.utils import INGIniousPage, INGIniousAuthPage
from inginious.frontend.task_dispensers.util import SectionsList
from inginious.frontend.accessible_time import parse_date
from collections import OrderedDict


PATH_TO_PLUGIN = os.path.abspath(os.path.dirname(__file__))

def menu(template_helper):
    """ Displays the link to the board on the main page, if the plugin is activated """
    return template_helper.render("main_menu.html", template_folder=PATH_TO_PLUGIN + '/templates/')


class StaticMockPage(INGIniousPage):
    def GET(self, path):
        return send_from_directory(os.path.join(PATH_TO_PLUGIN, "static"), path)

    def POST(self, path):
        return self.GET(path)


"""Returns a datetime object representing the deadline for a task
No deadline task are represented as deadline in 9999"""
def get_deadline_object(task):
    if task.get_accessible_time().is_always_accessible():
        return parse_date("18/03/9999 12:00:00", "%d/%m/%Y %H:%M:%S")
    elif task.get_accessible_time().is_never_accessible():
        return parse_date("18/03/9999 12:00:00", "%d/%m/%Y %H:%M:%S")
    else:
        return parse_date(task.get_deadline())

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

        """Get last submissions for left pannel"""
        last_submissions = self.submission_manager.get_user_last_submissions(5, {"courseid": {"$in": list(open_courses.keys())}})
        except_free_last_submissions = []
        for submission in last_submissions:
            try:
                submission["task"] = open_courses[submission['courseid']].get_task(submission['taskid'])
                except_free_last_submissions.append(submission)
            except:
                pass

        """Get the courses tasks, remove finished ones and courses that have no available unfinished tasks with deadline"""
        courses = {self.get_course(courseid): course for courseid, course in all_courses.items()
                        if self.user_manager.course_is_open_to_user(course, username, False) and
                        self.user_manager.course_is_user_registered(course, username)}
        tasks_data = {}
        outdated_tasks=[]
        for course in courses:
            tasks = course.get_tasks()
            for task in tasks:
                the_task = course.get_task(task)
                if (the_task.get_accessible_time().is_open()==False or (get_deadline_object(the_task) > (datetime.now()+timedelta(days=time_planner)) )): 
                    #Not open or no-deadline (for this page, no-deadline is considered as in year 9999)
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


        """Use a specific render object to avoid modifying the generic render"""
        my_render=Render_Ordered(username)
        time_planner = ["7", "14", "30", "unlimited"]

        """Sort the courses based on the most urgent task for each course"""
        open_courses = OrderedDict( sorted(iter(open_courses.items()), key=lambda x: get_deadline_object(self.get_closest_deadline(x[1], tasks_data)) ))
        return self.template_helper.render("coming_tasks.html",
                                           template_folder=PATH_TO_PLUGIN + "/templates/",
                                           open_courses=open_courses,
                                           tasks_data=tasks_data,
                                           my_render=my_render,
                                           time_planner=time_planner,
                                           submissions=except_free_last_submissions)

    """Get a course based on its courseid"""
    def get_course(self, courseid):
        try:
            course = self.course_factory.get_course(courseid)
        except:
            raise NotFound(description=_("Course not found."))
        return course


    """When given a course and list of user_task, found which task from this course is the most urgent for this user
    course is a Course object. user_task_list is the list of tasks available for the user which are not finished and have a deadline
    Returns the closest task (object)"""
    def get_closest_deadline(self, course, user_urgent_task_list):
        course_tasks = course.get_tasks()
        closest_deadline = parse_date("18/03/9999 12:00:00")
        closest_task = ""
        for taskid in course_tasks: #For task from the course 
            if (taskid in user_urgent_task_list): #If the task is urgent (not finished and there is a deadline)
                task = course.get_task(taskid)
                deadline = get_deadline_object(task)
                if (deadline < closest_deadline):
                    closest_deadline = deadline
                    closest_task = task
        return closest_task


    def time_planner_converstion(self, string_time_planner):
        if (string_time_planner=="unlimited"):
            return 10000
        else:
            return int(string_time_planner)

  
def init(plugin_manager, _, _2, config):
    """ Init the plugin """
    plugin_manager.add_page('/coming_tasks', UpComingTasksBoard.as_view("upcomingtasksboardpage"))
    plugin_manager.add_page('/plugins/coming_tasks/static/<path:path>', StaticMockPage.as_view("upcomingtasksstaticmockpage"))
    plugin_manager.add_hook('main_menu', menu)


"""Class representing a render which is sent to the html file where it is recursively called with jinja"""
class Render_Ordered:

    def __init__(self, username):
        self.username = username

    """Used to render the task list filtered on deadlines"""
    def render_upcoming_list(self, template_helper, course, tasks_data, tag_list):
        """ Returns the formatted task list"""
        task_list = course.get_task_dispenser().get_user_task_list([self.username])[self.username]
        task_list_function = course.get_tasks(True)
        initial_dispenser_data = course.get_task_dispenser().get_dispenser_data()
        """deepcopy to avoid modify data_dispenser (ordering tasks by deadline) without modifying the course structure"""
        new_dispenser_data = copy.deepcopy(initial_dispenser_data)
        """Order the tasks (no direct possibility to re-order the dispenser_data so remove tasks and put them back in deadline order"""
        ordered_tasks = []
        for item in initial_dispenser_data:
            section_task_list = sorted(item.get_tasks(), key= lambda x: get_deadline_object(course.get_task(x))) 
            ordered_tasks += section_task_list
        """Remove all the tasks"""
        for item in initial_dispenser_data:
            for task in item.get_tasks():
                new_dispenser_data.remove_task(task)
        """Add the tasks in deadline order"""
        for item in initial_dispenser_data:
            section = item.get_id() #the section has no importance since it is not rended in the html but id is required for add_task
        for task in ordered_tasks:
           new_dispenser_data.add_task(task, section)

        return template_helper.render("upcoming.html", template_folder=PATH_TO_PLUGIN + '/templates/', course=course, tasks=task_list_function, 
                                      tasks_data=tasks_data, tag_filter_list=tag_list, sections=new_dispenser_data)
